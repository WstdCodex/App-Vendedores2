# odoo_connection.py
import xmlrpc.client
from datetime import datetime, date
import base64

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

    def _format_date(self, value):
        """Convertir fechas de Odoo a formato legible."""
        if isinstance(value, (datetime, date)):
            return value.strftime('%d/%m/%Y')
        if isinstance(value, str):
            try:
                return datetime.strptime(value, '%Y-%m-%d').strftime('%d/%m/%Y')
            except ValueError:
                return value
        return ''

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
                        'payment_state', 'invoice_partner_display_name', 'invoice_user_id'
                    ]
                }
            )

            facturas_formateadas = []
            for factura in facturas:
                estado_pago = self._get_payment_state(factura)
                facturas_formateadas.append({
                    'id': factura['id'],
                    'nombre': factura['name'],
                    'fecha': self._format_date(factura.get('invoice_date')),
                    'cliente': factura.get('invoice_partner_display_name', 'Sin cliente'),
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
                        'payment_state', 'invoice_partner_display_name'
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
                    'fecha': self._format_date(factura.get('invoice_date')),
                    'cliente': factura.get('invoice_partner_display_name', 'Sin cliente'),
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

    def buscar_clientes(self, nombre_cliente: str = '', user_id: int = None, limit: int = 20):
        """Buscar clientes en Odoo asignados a un vendedor específico.
        
        IMPORTANTE: El user_id debe ser proporcionado obligatoriamente para filtrar
        solo los clientes asignados al comercial específico.
        """
        try:
            # Validación: user_id es obligatorio
            if user_id is None:
                print("Error: user_id es obligatorio para buscar clientes")
                return []

            domain = [
                ('customer_rank', '>', 0),
                ('parent_id', '=', False),
                ('user_id', '=', user_id)  # FILTRO CRÍTICO: Solo clientes de este vendedor
            ]
            
            if nombre_cliente:
                domain.append(('name', 'ilike', nombre_cliente))

            print(f"Buscando clientes con dominio: {domain}")

            # Utilizamos ``search_read`` con un límite para obtener los
            # datos de los clientes en una sola llamada y reducir el
            # tiempo de respuesta.
            clientes = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.partner',
                'search_read',
                [domain],
                {
                    'fields': ['name', 'credit', 'debit', 'user_id'],
                    'limit': limit,
                },
            )

            print(f"Clientes encontrados: {len(clientes) if clientes else 0}")

            if not clientes:
                return []

            clientes_formateados = []
            for c in clientes:
                # Verificación adicional del vendedor asignado
                cliente_user_id = c.get('user_id')
                if cliente_user_id:
                    cliente_user_id = cliente_user_id[0] if isinstance(cliente_user_id, list) else cliente_user_id
                
                # Si el cliente no tiene el vendedor correcto, lo saltamos
                if cliente_user_id != user_id:
                    print(f"Cliente {c.get('name')} tiene vendedor {cliente_user_id}, esperado {user_id}")
                    continue

                # Calcular la deuda total sumando los montos pendientes de las
                # facturas publicadas del cliente.
                deuda_total = 0.0
                try:
                    facturas_pendientes = self.models.execute_kw(
                        self.db,
                        self.uid,
                        self.password,
                        'account.move',
                        'search_read',
                        [[
                            ('move_type', '=', 'out_invoice'),
                            ('partner_id', '=', c['id']),
                            ('state', '=', 'posted'),
                            ('amount_residual', '>', 0),
                        ]],
                        {'fields': ['amount_residual']},
                    )
                    deuda_total = sum(
                        f.get('amount_residual', 0.0) for f in facturas_pendientes
                    )
                except Exception:
                    deuda_total = 0.0

                credito = c.get('credit', 0.0)
                debito = c.get('debit', 0.0)
                saldo_favor = max(credito - debito, 0.0)
                clientes_formateados.append(
                    {
                        'id': c['id'],
                        'nombre': c.get('name', ''),
                        'deuda_total': deuda_total,
                        'saldo_favor': saldo_favor,
                        'vendedor_id': cliente_user_id  # Para debug
                    }
                )

            print(f"Clientes formateados: {len(clientes_formateados)}")
            return clientes_formateados
            
        except Exception as e:
            print(f"Error buscando clientes: {e}")
            return []

    def get_clientes_vendedor(self, user_id: int, nombre_cliente: str = '', limit: int = 20):
        """Método específico para obtener SOLO los clientes asignados a un vendedor específico.
        
        Este método garantiza que solo se devuelvan clientes que tengan el vendedor
        especificado en el campo 'user_id' del modelo res.partner.
        """
        try:
            if user_id is None:
                print("Error: user_id es obligatorio")
                return []

            # Dominio estricto: solo clientes con este vendedor específico
            domain = [
                ('customer_rank', '>', 0),          # Es un cliente
                ('parent_id', '=', False),          # No es un contacto hijo
                ('user_id', '=', user_id),          # Asignado a este vendedor específicamente
                ('active', '=', True)               # Cliente activo
            ]
            
            if nombre_cliente.strip():
                domain.append(('name', 'ilike', f'%{nombre_cliente.strip()}%'))

            print(f"Dominio de búsqueda: {domain}")

            # Buscar clientes con el dominio específico
            clientes = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.partner',
                'search_read',
                [domain],
                {
                    'fields': ['name', 'credit', 'debit', 'user_id', 'email', 'phone'],
                    'limit': limit,
                    'order': 'name ASC'
                },
            )

            print(f"Número de clientes encontrados: {len(clientes) if clientes else 0}")

            if not clientes:
                return []

            clientes_formateados = []
            for c in clientes:
                # Doble verificación del vendedor
                cliente_vendedor = c.get('user_id')
                if cliente_vendedor:
                    vendedor_id = cliente_vendedor[0] if isinstance(cliente_vendedor, list) else cliente_vendedor
                    if vendedor_id != user_id:
                        print(f"ADVERTENCIA: Cliente {c.get('name')} tiene vendedor {vendedor_id}, esperado {user_id}")
                        continue

                # Calcular deuda total
                deuda_total = 0.0
                try:
                    facturas_pendientes = self.models.execute_kw(
                        self.db,
                        self.uid,
                        self.password,
                        'account.move',
                        'search_read',
                        [[
                            ('move_type', '=', 'out_invoice'),
                            ('partner_id', '=', c['id']),
                            ('state', '=', 'posted'),
                            ('amount_residual', '>', 0),
                        ]],
                        {'fields': ['amount_residual']},
                    )
                    deuda_total = sum(
                        f.get('amount_residual', 0.0) for f in facturas_pendientes
                    )
                except Exception as e:
                    print(f"Error calculando deuda para cliente {c['id']}: {e}")
                    deuda_total = 0.0

                credito = c.get('credit', 0.0)
                debito = c.get('debit', 0.0)
                saldo_favor = max(credito - debito, 0.0)
                
                clientes_formateados.append({
                    'id': c['id'],
                    'nombre': c.get('name', ''),
                    'email': c.get('email', ''),
                    'telefono': c.get('phone', ''),
                    'deuda_total': deuda_total,
                    'saldo_favor': saldo_favor,
                })

            print(f"Clientes procesados correctamente: {len(clientes_formateados)}")
            return clientes_formateados

        except Exception as e:
            print(f"Error obteniendo clientes del vendedor: {e}")
            return []

    def get_cliente(self, partner_id):
        """Obtener información del cliente"""
        try:
            cliente = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.partner',
                'read',
                [partner_id],
                {
                    'fields': ['name', 'email', 'phone', 'street', 'credit', 'debit', 'user_id']
                },
            )
            if cliente:
                c = cliente[0]
                # Calcular la deuda total sumando los montos pendientes de las
                # facturas publicadas del cliente.
                deuda_total = 0.0
                try:
                    facturas_pendientes = self.models.execute_kw(
                        self.db,
                        self.uid,
                        self.password,
                        'account.move',
                        'search_read',
                        [[
                            ('move_type', '=', 'out_invoice'),
                            ('partner_id', '=', c['id']),
                            ('state', '=', 'posted'),
                            ('amount_residual', '>', 0),
                        ]],
                        {'fields': ['amount_residual']},
                    )
                    deuda_total = sum(
                        f.get('amount_residual', 0.0) for f in facturas_pendientes
                    )
                except Exception:
                    deuda_total = 0.0

                credito = c.get('credit', 0.0)
                debito = c.get('debit', 0.0)
                saldo_favor = max(credito - debito, 0.0)
                
                # Obtener información del vendedor asignado
                vendedor_info = ""
                if c.get('user_id'):
                    vendedor_id = c['user_id'][0] if isinstance(c['user_id'], list) else c['user_id']
                    try:
                        vendedor = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'res.users', 'read',
                            [vendedor_id], {'fields': ['name']}
                        )
                        if vendedor:
                            vendedor_info = vendedor[0]['name']
                    except Exception:
                        pass
                
                return {
                    'id': c.get('id'),
                    'nombre': c.get('name', ''),
                    'email': c.get('email', ''),
                    'telefono': c.get('phone', ''),
                    'direccion': c.get('street', ''),
                    'deuda_total': deuda_total,
                    'saldo_favor': saldo_favor,
                    'vendedor': vendedor_info,
                    'vendedor_id': c.get('user_id')[0] if c.get('user_id') else None
                }
            return {}
        except Exception as e:
            print(f"Error obteniendo cliente: {e}")
            return {}

    def get_facturas_cliente(self, partner_id, codigo_factura='', estado_filtro=''):
        """Obtener facturas publicadas de un cliente con filtros"""
        try:
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('partner_id', '=', partner_id),
                ('state', '=', 'posted')
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
                    'fecha': self._format_date(factura.get('invoice_date')),
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

    def get_factura(self, factura_id):
        """Obtener los detalles de una factura específica"""
        try:
            factura = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [factura_id],
                {
                    'fields': [
                        'name', 'invoice_date', 'amount_total',
                        'invoice_partner_display_name', 'invoice_line_ids'
                    ]
                }
            )
            if not factura:
                return None

            f = factura[0]
            lineas = []
            if f.get('invoice_line_ids'):
                lineas_data = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'account.move.line', 'read',
                    [f['invoice_line_ids']],
                    {'fields': ['name', 'quantity', 'price_unit', 'price_total']}
                )
                lineas = [
                    {
                        'descripcion': l.get('name', ''),
                        'cantidad': l.get('quantity', 0),
                        'precio_unitario': l.get('price_unit', 0.0),
                        'subtotal': l.get('price_total', 0.0)
                    }
                    for l in lineas_data
                ]

            return {
                'id': f.get('id'),
                'nombre': f.get('name'),
                'fecha': self._format_date(f.get('invoice_date')),
                'cliente': f.get('invoice_partner_display_name', ''),
                'total': f.get('amount_total', 0.0),
                'lineas': lineas
            }
        except Exception as e:
            print(f"Error obteniendo factura: {e}")
            return None

    def get_factura_pdf(self, factura_id):
        """Obtener el PDF de una factura"""
        try:
            # Algunos servidores Odoo usan distintos nombres para el reporte de factura.
            # Probamos con una lista de nombres comunes antes de recurrir a búsquedas.
            report_names = [
                'account.report_invoice_with_payments',
                'account.report_invoice',
                'account.report_invoice_document',
            ]

            last_exception = None
            for report_name in report_names:
                try:
                    pdf = self.models.execute_kw(
                        self.db,
                        self.uid,
                        self.password,
                        'ir.actions.report',
                        '_render_qweb_pdf',
                        [report_name, [factura_id]],
                    )
                    break
                except Exception as e1:
                    last_exception = e1
                    pdf = None

            if pdf is None:
                raise last_exception  # Propaga la última excepción para manejarla abajo

            # Procesar el resultado del PDF
            if isinstance(pdf, dict) and pdf.get('result'):
                pdf_content = pdf['result']
            elif isinstance(pdf, (list, tuple)) and len(pdf) > 0:
                pdf_content = pdf[0]
            else:
                pdf_content = pdf

            # Decodificar si es string base64
            if isinstance(pdf_content, str):
                return base64.b64decode(pdf_content)
            return pdf_content

        except Exception as e:
            print(f"Método directo falló: {e}")
            try:
                # Búsqueda alternativa: encontrar el reporte PDF para account.move
                report = self.models.execute_kw(
                    self.db,
                    self.uid,
                    self.password,
                    'ir.actions.report',
                    'search_read',
                    [[('model', '=', 'account.move'), ('report_type', '=', 'qweb-pdf')]],
                    {'fields': ['id'], 'limit': 1},
                )

                if not report:
                    print("No se encontró un reporte PDF para account.move")
                    return None

                report_id = report[0]['id']

                pdf = self.models.execute_kw(
                    self.db,
                    self.uid,
                    self.password,
                    'ir.actions.report',
                    '_render_qweb_pdf',
                    [report_id, [factura_id]],
                )

                if isinstance(pdf, dict) and pdf.get('result'):
                    pdf_content = pdf['result']
                elif isinstance(pdf, (list, tuple)) and len(pdf) > 0:
                    pdf_content = pdf[0]
                else:
                    pdf_content = pdf

                if isinstance(pdf_content, str):
                    return base64.b64decode(pdf_content)
                return pdf_content

            except Exception as e2:
                print(f"Error obteniendo PDF de factura: {e2}")
                return None
