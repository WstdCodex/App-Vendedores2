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
        """Buscar clientes en Odoo asignados a un vendedor.


        Solo se devolverán los clientes cuyo vendedor responsable
        coincida con el identificador proporcionado. Se limita el número
        de resultados para evitar demoras al consultar grandes cantidades
        de registros."""
        try:
            domain = [
                ('customer_rank', '>', 0),

                ('parent_id', '=', False),

            ]
            if nombre_cliente:
                domain.append(('name', 'ilike', nombre_cliente))
            if user_id is not None:
                domain.append(('user_id', '=', user_id))

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
                    'fields': ['name', 'credit', 'debit'],
                    'limit': limit,
                },
            )

            if not clientes:
                return []

            clientes_formateados = []
            for c in clientes:
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
                    }
                )

            return clientes_formateados
        except Exception as e:
            print(f"Error buscando clientes: {e}")
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
                    'fields': ['name', 'email', 'phone', 'street', 'credit', 'debit']
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
                return {
                    'id': c.get('id'),
                    'nombre': c.get('name', ''),
                    'email': c.get('email', ''),
                    'telefono': c.get('phone', ''),
                    'direccion': c.get('street', ''),
                    'deuda_total': deuda_total,
                    'saldo_favor': saldo_favor,
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
            # Método 1: Usar _render_qweb_pdf directamente con el nombre del reporte
            pdf = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'ir.actions.report',
                '_render_qweb_pdf',
                ['account.report_invoice', [factura_id]],
            )

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
            else:
                return pdf_content

        except Exception as e:
            print(f"Método 1 falló: {e}")
            try:
                # Método 2: Buscar el reporte por su external_id y usar su ID
                report_data = self.models.execute_kw(
                    self.db,
                    self.uid,
                    self.password,
                    'ir.model.data',
                    'search_read',
                    [[('name', '=', 'report_invoice'), ('module', '=', 'account')]],
                    {'fields': ['res_id']}
                )

                if not report_data:
                    print("No se encontró el reporte de factura")
                    return None

                report_id = report_data[0]['res_id']

                pdf = self.models.execute_kw(
                    self.db,
                    self.uid,
                    self.password,
                    'ir.actions.report',
                    '_render_qweb_pdf',
                    [report_id, [factura_id]],
                )

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
                else:
                    return pdf_content

            except Exception as e2:
                print(f"Método 2 también falló: {e2}")
                try:
                    # Método 3: Usar render_qweb_pdf alternativo
                    pdf = self.models.execute_kw(
                        self.db,
                        self.uid,
                        self.password,
                        'ir.actions.report',
                        'render_qweb_pdf',
                        ['account.report_invoice', [factura_id]],
                    )

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
                    else:
                        return pdf_content

                except Exception as e3:
                    print(f"Error obteniendo PDF de factura (todos los métodos fallaron): {e3}")
                    return None

