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
            return 'success'
        elif estado == 'partial':
            return 'warning'
        return 'danger'

    def get_estado_texto(self, estado):
        """Obtener texto del estado en español"""
        estados = {
            'paid': 'Pagado',
            'partial': 'Pagado Parcialmente',
            'not_paid': 'No Pagado'
        }
        return estados.get(estado, 'Desconocido')

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
        except Exception:
            return {}

    def _get_payment_state(self, factura):
        """Determinar el estado de pago basado en los montos"""
        if factura['amount_residual'] <= 0:
            return 'paid'
        elif factura['amount_residual'] < factura['amount_total']:
            return 'partial'
        return 'not_paid'

    def get_vendedor_facturas(self, user_id):
        """Obtener facturas del vendedor"""
        try:
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search',
                [[
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_user_id', '=', user_id),
                    ('state', '!=', 'draft')
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
                        'payment_state', 'partner_id', 'invoice_user_id'
                    ]
                }
            )

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

    def buscar_facturas(self, user_id, codigo_factura='', estado_filtro=''):
        """Buscar facturas con filtros"""
        try:
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('invoice_user_id', '=', user_id),
                ('state', '!=', 'draft')
            ]
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

            facturas_filtradas = []
            for factura in facturas:
                estado_pago = self._get_payment_state(factura)
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

    def buscar_clientes(self, user_id, nombre_cliente=''):
        """Buscar clientes asignados al vendedor"""
        try:
            domain = [
                ('user_id', '=', user_id),
                ('customer_rank', '>', 0)
            ]
            if nombre_cliente:
                domain.append(('name', 'ilike', nombre_cliente))

            clientes_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'res.partner', 'search', [domain]
            )
            if not clientes_ids:
                return []

            clientes = self.models.execute_kw(
                self.db, self.uid, self.password,
                'res.partner', 'read',
                [clientes_ids],
                {'fields': ['name']}
            )

            return [
                {
                    'id': c['id'],
                    'nombre': c.get('name', '')
                }
                for c in clientes
            ]
        except Exception as e:
            print(f"Error buscando clientes: {e}")
            return []

    def get_cliente(self, partner_id):
        """Obtener información del cliente"""
        try:
            cliente = self.models.execute_kw(
                self.db, self.uid, self.password,
                'res.partner', 'read',
                [partner_id],
                {'fields': ['name', 'email', 'phone', 'street']}
            )
            if cliente:
                c = cliente[0]
                return {
                    'id': c.get('id'),
                    'nombre': c.get('name', ''),
                    'email': c.get('email', ''),
                    'telefono': c.get('phone', ''),
                    'direccion': c.get('street', '')
                }
            return {}
        except Exception as e:
            print(f"Error obteniendo cliente: {e}")
            return {}

    def get_facturas_cliente(self, user_id, partner_id, codigo_factura='', estado_filtro=''):
        """Obtener facturas de un cliente con filtros"""
        try:
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('invoice_user_id', '=', user_id),
                ('partner_id', '=', partner_id),
                ('state', '!=', 'draft')
            ]
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
                        'payment_state'
                    ]
                }
            )

            facturas_formateadas = []
            for factura in facturas:
                estado_pago = self._get_payment_state(factura)
                if estado_filtro and estado_pago != estado_filtro:
                    continue
                facturas_formateadas.append({
                    'id': factura['id'],
                    'nombre': factura['name'],
                    'fecha': factura['invoice_date'].strftime('%d/%m/%Y') if factura['invoice_date'] else '',
                    'total': factura['amount_total'],
                    'pendiente': factura['amount_residual'],
                    'estado': estado_pago,
                    'estado_texto': self.get_estado_texto(estado_pago),
                    'estado_color': self.get_estado_color(estado_pago)
                })
            return facturas_formateadas
        except Exception as e:
            print(f"Error obteniendo facturas del cliente: {e}")
            return []

