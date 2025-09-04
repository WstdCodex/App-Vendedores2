# odoo_connection.py
import xmlrpc.client
from datetime import datetime

class OdooConnection:
    def __init__(self, url, db, username, password):
        self.url = url
        self.db = db
        self.username = username
        self.password = password
        self.uid = None
        
        # Conexiones XML-RPC
        self.common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        self.models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
    
    def authenticate(self):
        """Autenticar usuario en Odoo"""
        try:
            self.uid = self.common.authenticate(self.db, self.username, self.password, {})
            if self.uid:
                # Obtener información del usuario
                user_info = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'res.users', 'read',
                    [self.uid], {'fields': ['name', 'login', 'partner_id']}
                )
                return {
                    'user_id': self.uid,
                    'name': user_info[0]['name'],
                    'partner_id': user_info[0]['partner_id'][0] if user_info[0]['partner_id'] else None
                }
            return None
        except Exception as e:
            print(f"Error de autenticación: {e}")
            return None
    
    def get_estado_color(self, estado):
        """Obtener color según el estado de pago"""
        if estado == 'paid':
            return 'success'  # Verde
        elif estado == 'partial':
            return 'warning'  # Naranja
        else:  # not_paid
            return 'danger'   # Rojo
    
    def get_estado_texto(self, estado):
        """Obtener texto del estado en español"""
        estados = {
            'paid': 'Pagado',
            'partial': 'Pagado Parcialmente',
            'not_paid': 'No Pagado'
        }
        return estados.get(estado, 'Desconocido')
    
    def get_vendedor_facturas(self, user_id):
        """Obtener facturas del vendedor"""
        try:
            # Buscar facturas donde el vendedor sea el usuario actual
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search',
                [[
                    ('move_type', '=', 'out_invoice'),  # Solo facturas de cliente
                    ('invoice_user_id', '=', user_id),   # Vendedor
                    ('state', '=', 'posted')             # Solo facturas validadas
                ]]
            )
            
            if not facturas_ids:
                return []
            
            # Obtener datos de las facturas
            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [facturas_ids],
                {
                    'fields': [
                        'name', 'invoice_date', 'amount_total', 'amount_residual',
                        'payment_state', 'partner_id', 'invoice_user_id'
                    ]
                }
            )
            
            # Formatear datos
            facturas_formateadas = []
            for factura in facturas:
                estado_pago = self._get_payment_state(factura)
                facturas_formateadas.append({
                    'id': factura['id'],
                    'nombre': factura['name'],
                    'fecha': factura['invoice_date'].strftime('%d/%m/%Y') if factura['invoice_date'] else '',
                    'cliente': factura['partner_id'][1] if factura['partner_id'] else 'Sin cliente',
                    'total': factura['amount_total'],
                    'pendiente': factura['amount_residual'],
                    'estado': estado_pago,
                    'estado_texto': self.get_estado_texto(estado_pago),
                    'estado_color': self.get_estado_color(estado_pago)
                })
            
            return facturas_formateadas
            
        except Exception as e:
            print(f"Error obteniendo facturas del vendedor: {e}")
            return []
    
    def get_clientes_facturas(self, user_id):
        """Obtener clientes y sus facturas del vendedor"""
        try:
            # Obtener facturas del vendedor con información del cliente
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search',
                [[
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_user_id', '=', user_id),
                    ('state', '=', 'posted')
                ]]
            )
            
            if not facturas_ids:
                return []
            
            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [facturas_ids],
                {
                    'fields': [
                        'name', 'invoice_date', 'amount_total', 'amount_residual',
                        'payment_state', 'partner_id'
                    ]
                }
            )
            
            # Agrupar por cliente
            clientes_dict = {}
            for factura in facturas:
                if factura['partner_id']:
                    partner_id = factura['partner_id'][0]
                    partner_name = factura['partner_id'][1]
                    
                    if partner_id not in clientes_dict:
                        # Obtener datos adicionales del cliente
                        cliente_info = self._get_cliente_info(partner_id)
                        clientes_dict[partner_id] = {
                            'id': partner_id,
                            'nombre': partner_name,
                            'email': cliente_info.get('email', ''),
                            'telefono': cliente_info.get('phone', ''),
                            'direccion': cliente_info.get('street', ''),
                            'facturas': []
                        }
                    
                    estado_pago = self._get_payment_state(factura)
                    clientes_dict[partner_id]['facturas'].append({
                        'id': factura['id'],
                        'nombre': factura['name'],
                        'fecha': factura['invoice_date'].strftime('%d/%m/%Y') if factura['invoice_date'] else '',
                        'total': factura['amount_total'],
                        'pendiente': factura['amount_residual'],
                        'estado': estado_pago,
                        'estado_texto': self.get_estado_texto(estado_pago),
                        'estado_color': self.get_estado_color(estado_pago)
                    })
            
            return list(clientes_dict.values())
            
        except Exception as e:
            print(f"Error obteniendo clientes y facturas: {e}")
            return []
    
    def _get_cliente_info(self, partner_id):
        """Obtener información adicional del cliente"""
        try:
            cliente = self.models.execute_kw(
                self.db, self.uid, self.password,
                'res.partner', 'read',
                [partner_id],
                {'fields': ['email', 'phone', 'street', 'city', 'country_id']}
            )
            return cliente[0] if cliente else {}
        except:
            return {}
    
    def _get_payment_state(self, factura):
        """Determinar el estado de pago basado en los montos"""
        if factura['amount_residual'] <= 0:
            return 'paid'
        elif factura['amount_residual'] < factura['amount_total']:
            return 'partial'
        else:
            return 'not_paid'
    
    def buscar_facturas(self, user_id, codigo_factura='', estado_filtro=''):
        """Buscar facturas con filtros"""
        try:
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('invoice_user_id', '=', user_id),
                ('state', '=', 'posted')
            ]
            
            # Filtro por código de factura
            if codigo_factura:
                domain.append(('name', 'ilike', codigo_factura))
            
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search', [domain]
            )
            
            if not facturas_ids:
                return []
            
            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [facturas_ids],
                {
                    'fields': [
                        'name', 'invoice_date', 'amount_total', 'amount_residual',
                        'payment_state', 'partner_id'
                    ]
                }
            )
            
            # Formatear y filtrar por estado
            facturas_filtradas = []
            for factura in facturas:
                estado_pago = self._get_payment_state(factura)
                
                # Aplicar filtro de estado
                if estado_filtro and estado_pago != estado_filtro:
                    continue
                
                facturas_filtradas.append({
                    'id': factura['id'],
                    'nombre': factura['name'],
                    'fecha': factura['invoice_date'].strftime('%d/%m/%Y') if factura['invoice_date'] else '',
                    'cliente': factura['partner_id'][1] if factura['partner_id'] else 'Sin cliente',
                    'total': factura['amount_total'],
                    'pendiente': factura['amount_residual'],
                    'estado': estado_pago,
                    'estado_texto': self.get_estado_texto(estado_pago),
                    'estado_color': self.get_estado_color(estado_pago)
                })
            
            return facturas_filtradas
            
        except Exception as e:
            print(f"Error buscando facturas: {e}")
            return []
    
    def buscar_clientes(self, user_id, nombre_cliente='', codigo_factura='', estado_filtro=''):
        """Buscar clientes con filtros"""
        try:
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('invoice_user_id', '=', user_id),
                ('state', '=', 'posted')
            ]
            
            # Filtros
            if codigo_factura:
                domain.append(('name', 'ilike', codigo_factura))
            
            if nombre_cliente:
                # Buscar por nombre del cliente
                clientes_ids = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'res.partner', 'search',
                    [[('name', 'ilike', nombre_cliente)]]
                )
                if clientes_ids:
                    domain.append(('partner_id', 'in', clientes_ids))
                else:
                    return []
            
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search', [domain]
            )
            
            if not facturas_ids:
                return []
            
            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [facturas_ids],
                {
                    'fields': [
                        'name', 'invoice_date', 'amount_total', 'amount_residual',
                        'payment_state', 'partner_id'
                    ]
                }
            )
            
            # Agrupar y filtrar
            clientes_dict = {}
            for factura in facturas:
                if factura['partner_id']:
                    estado_pago = self._get_payment_state(factura)
                    
                    # Aplicar filtro de estado
                    if estado_filtro and estado_pago != estado_filtro:
                        continue
                    
                    partner_id = factura['partner_id'][0]
                    partner_name = factura['partner_id'][1]
                    
                    if partner_id not in clientes_dict:
                        cliente_info = self._get_cliente_info(partner_id)
                        clientes_dict[partner_id] = {
                            'id': partner_id,
                            'nombre': partner_name,
                            'email': cliente_info.get('email', ''),
                            'telefono': cliente_info.get('phone', ''),
                            'direccion': cliente_info.get('street', ''),
                            'facturas': []
                        }
                    
                    clientes_dict[partner_id]['facturas'].append({
                        'id': factura['id'],
                        'nombre': factura['name'],
                        'fecha': factura['invoice_date'].strftime('%d/%m/%Y') if factura['invoice_date'] else '',
                        'total': factura['amount_total'],
                        'pendiente': factura['amount_residual'],
                        'estado': estado_pago,
                        'estado_texto': self.get_estado_texto(estado_pago),
                        'estado_color': self.get_estado_color(estado_pago)
                    })
            
            return list(clientes_dict.values())
            
        except Exception as e:
            print(f"Error buscando clientes: {e}")
            return []