# odoo_connection.py
import xmlrpc.client
from datetime import datetime, date
from calendar import monthrange
import base64
import json

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

    def has_group(self, group_xml_id: str) -> bool:
        """Verificar si el usuario autenticado pertenece a un grupo específico.

        Parameters
        ----------
        group_xml_id: str
            Identificador XML del grupo, por ejemplo
            ``'sales_team.group_sale_manager'``.

        Returns
        -------
        bool
            ``True`` si el usuario pertenece al grupo, ``False`` en caso
            contrario o si ocurre un error.
        """
        try:
            return self.models.execute_kw(
                self.db, self.uid, self.password,
                'res.users', 'has_group', [group_xml_id]
            )
        except Exception as e:
            print(f"Error comprobando grupo {group_xml_id}: {e}")
            return False

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

    def get_total_gastos_mes(self, user_id, year, month):
        """Obtener el total facturado en un mes específico.

        Si ``user_id`` es ``None`` se calcula el total de todos los
        vendedores; en caso contrario solo del vendedor indicado.
        """
        try:
            start_date = datetime(year, month, 1).strftime('%Y-%m-%d')
            end_day = monthrange(year, month)[1]
            end_date = datetime(year, month, end_day).strftime('%Y-%m-%d')
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'draft'),
                ('invoice_date', '>=', start_date),
                ('invoice_date', '<=', end_date),
            ]
            if user_id is not None:
                domain.append(('invoice_user_id', '=', user_id))
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search', [domain]
            )
            if not facturas_ids:
                return 0.0
            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [facturas_ids], {'fields': ['amount_total']}
            )
            return sum(f.get('amount_total', 0.0) for f in facturas)
        except Exception as e:
            print(f"Error obteniendo total mensual: {e}")
            return 0.0

    def get_total_gasto_cliente_mes(self, partner_id, year, month):
        """Obtener el total gastado por un cliente en un mes específico."""
        try:
            start_date = datetime(year, month, 1).strftime('%Y-%m-%d')
            end_day = monthrange(year, month)[1]
            end_date = datetime(year, month, end_day).strftime('%Y-%m-%d')
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('partner_id', '=', partner_id),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', start_date),
                ('invoice_date', '<=', end_date),
            ]
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search', [domain]
            )
            if not facturas_ids:
                return 0.0
            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [facturas_ids], {'fields': ['amount_total']}
            )
            return sum(f.get('amount_total', 0.0) for f in facturas)
        except Exception as e:
            print(f"Error obteniendo gasto mensual del cliente: {e}")
            return 0.0

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

    def get_provincias(self):

        """Obtener solo las provincias argentinas disponibles en Odoo."""
        try:
            # Buscar el país Argentina por su código ISO
            country_ids = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.country',
                'search',
                [[('code', '=', 'AR')]],
                {'limit': 1},
            )

            if not country_ids:
                return []


            provincias = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.country.state',
                'search_read',

                [[('country_id', '=', country_ids[0])]],

                {
                    'fields': ['name'],
                    'order': 'name ASC'
                },
            )
            return [{'id': p['id'], 'nombre': p['name']} for p in provincias]
        except Exception as e:
            print(f"Error obteniendo provincias: {e}")
            return []

    def get_ciudades(self, state_id=None, user_id=None):
        """Obtener lista de ciudades disponibles, opcionalmente filtradas por provincia y vendedor."""
        try:
            domain = [('city', '!=', False)]
            if state_id:
                domain.append(('state_id', '=', state_id))
            if user_id is not None:
                domain.extend([
                    ('user_id', '=', user_id),
                    ('customer_rank', '>', 0),
                    ('parent_id', '=', False)
                ])

            partners = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.partner',
                'search_read',
                [domain],
                {'fields': ['city', 'state_id']},
            )

            ciudades = sorted({p['city'] for p in partners if p.get('city')})
            return [{'nombre': c} for c in ciudades]
        except Exception as e:
            print(f"Error obteniendo ciudades: {e}")
            return []

    def buscar_clientes(self, nombre_cliente: str = '', user_id: int = None,
                         limit: int = 20, provincia_id: int = None,
                         ciudad: str = ''):
        """Buscar clientes en Odoo, opcionalmente filtrados por vendedor.

        Cuando ``user_id`` es ``None`` se devuelven todos los clientes
        disponibles; en caso contrario solo aquellos asignados al vendedor
        especificado. Además permite filtrar por provincia (``state_id``) y
        ciudad.
        """
        try:
            domain = [
                ('customer_rank', '>', 0),
                ('parent_id', '=', False),
            ]
            if user_id is not None:
                domain.append(('user_id', '=', user_id))

            if nombre_cliente:
                domain.append(('name', 'ilike', nombre_cliente))
            if provincia_id:
                domain.append(('state_id', '=', provincia_id))
            if ciudad:
                domain.append(('city', 'ilike', ciudad))

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

                # Si se solicita filtrar por vendedor y no coincide, lo saltamos
                if user_id is not None and cliente_user_id != user_id:
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
                        'name',
                        'invoice_date',
                        'amount_total',
                        'invoice_partner_display_name',
                        'invoice_line_ids',
                        'tax_totals_json',
                        'amount_residual',
                        'l10n_ar_afip_auth_code',
                        'l10n_ar_afip_auth_code_due',
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
                    {
                        'fields': [
                            'name', 'quantity', 'price_unit',
                            'price_total', 'price_subtotal'
                        ]
                    }
                )
                lineas = [
                    {
                        'descripcion': l.get('name', ''),
                        'cantidad': l.get('quantity', 0),
                        'precio_unitario': l.get('price_unit', 0.0),
                        'iva': l.get('price_total', 0.0) - l.get('price_subtotal', 0.0),
                        'total': l.get('price_total', 0.0)
                    }
                    for l in lineas_data
                ]

            tax_totals = {}
            try:
                tax_totals = json.loads(f.get('tax_totals_json') or '{}')
            except Exception:
                tax_totals = {}
            amount_untaxed = tax_totals.get('amount_untaxed', 0.0)
            iva_21 = 0.0
            perc_iibb = 0.0
            groups = tax_totals.get('groups_by_subtotal', {})
            for group_lines in groups.values():
                for g in group_lines:
                    name = (g.get('tax_group_name') or g.get('name') or '').upper()
                    if 'IVA 21' in name:
                        iva_21 += g.get('tax_group_amount', 0.0)
                    if 'PERC IIBB ARBA' in name:
                        perc_iibb += g.get('tax_group_amount', 0.0)

            return {
                'id': f.get('id'),
                'nombre': f.get('name'),
                'fecha': self._format_date(f.get('invoice_date')),
                'cliente': f.get('invoice_partner_display_name', ''),
                'total': f.get('amount_total', 0.0),
                'importe_untaxed': amount_untaxed,
                'iva_21': iva_21,
                'perc_iibb_arba': perc_iibb,
                'amount_residual': f.get('amount_residual', 0.0),
                'cae': f.get('l10n_ar_afip_auth_code', ''),
                'cae_due_date': self._format_date(
                    f.get('l10n_ar_afip_auth_code_due')
                ),
                'lineas': lineas
            }
        except Exception as e:
            print(f"Error obteniendo factura: {e}")
            return None

    def get_factura_pdf(self, factura_id):
        """Obtener el PDF de una factura - Versión para Odoo 15 Community"""
        try:
            # Método 1: Usar el reporte directamente con _generate_pdf si existe
            try:
                # Primero obtenemos el reporte de factura
                reports = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'ir.actions.report', 'search',
                    [[
                        ('model', '=', 'account.move'),
                        ('report_type', '=', 'qweb-pdf')
                    ]], {'limit': 1}
                )

                if reports:
                    report_id = reports[0]

                    # Obtener el objeto reporte
                    report_data = self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'ir.actions.report', 'read',
                        [report_id], {'fields': ['report_name']}
                    )

                    if report_data:
                        report_name = report_data[0]['report_name']

                        # Intentar con _generate_pdf
                        try:
                            pdf_result = self.models.execute_kw(
                                self.db, self.uid, self.password,
                                'ir.actions.report', '_generate_pdf',
                                [report_id, [factura_id]]
                            )

                            if pdf_result:
                                # _generate_pdf puede devolver el PDF directamente o en una estructura
                                if isinstance(pdf_result, bytes):
                                    return pdf_result
                                elif isinstance(pdf_result, str):
                                    return base64.b64decode(pdf_result)
                                elif isinstance(pdf_result, (list, tuple)) and len(pdf_result) > 0:
                                    pdf_content = pdf_result[0]
                                    if isinstance(pdf_content, str):
                                        return base64.b64decode(pdf_content)
                                    return pdf_content

                        except Exception as e:
                            print(f"Error con _generate_pdf: {e}")

            except Exception as e:
                print(f"Error método 1: {e}")

            # Método 2: Usar el método _render_template si existe
            try:
                reports = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'ir.actions.report', 'search_read',
                    [[
                        ('model', '=', 'account.move'),
                        ('report_type', '=', 'qweb-pdf')
                    ]],
                    {'fields': ['id', 'report_name'], 'limit': 1}
                )

                if reports:
                    report_id = reports[0]['id']

                    try:
                        pdf_result = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'ir.actions.report', '_render_template',
                            [report_id, [factura_id]]
                        )

                        if pdf_result:
                            if isinstance(pdf_result, bytes):
                                return pdf_result
                            elif isinstance(pdf_result, str):
                                return base64.b64decode(pdf_result)

                    except Exception as e:
                        print(f"Error con _render_template: {e}")

            except Exception as e:
                print(f"Error método 2: {e}")

            # Método 3: Usar el contexto de la factura para obtener el reporte
            try:
                # Obtener la acción de impresión de la factura
                action_result = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'account.move', 'action_invoice_print',
                    [[factura_id]]
                )

                if isinstance(action_result, dict):
                    report_id = action_result.get('id')
                    report_name = action_result.get('report_name')

                    if report_id:
                        try:
                            # Usar browse y print_document si está disponible
                            pdf_result = self.models.execute_kw(
                                self.db, self.uid, self.password,
                                'ir.actions.report', 'browse',
                                [report_id]
                            )

                            if pdf_result:
                                # Intentar generar el PDF
                                pdf_content = self.models.execute_kw(
                                    self.db, self.uid, self.password,
                                    'ir.actions.report', 'render_qweb_pdf',
                                    [[report_id], [factura_id]]
                                )

                                if pdf_content:
                                    if isinstance(pdf_content, (list, tuple)):
                                        return pdf_content[0] if pdf_content else None
                                    return pdf_content

                        except Exception as e:
                            print(f"Error con browse/render: {e}")

            except Exception as e:
                print(f"Error método 3: {e}")

            # Método 4: Enfoque directo con wkhtmltopdf si está disponible
            try:
                # Obtener el HTML de la factura primero
                reports = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'ir.actions.report', 'search_read',
                    [[('model', '=', 'account.move')]],
                    {'fields': ['id', 'report_name'], 'limit': 1}
                )

                if reports:
                    report_id = reports[0]['id']

                    # Intentar obtener el HTML primero
                    try:
                        html_result = self.models.execute_kw(
                            self.db, self.uid, self.password,
                            'ir.actions.report', '_render_qweb_html',
                            [report_id, [factura_id]]
                        )

                        if html_result:
                            print("HTML obtenido, pero necesitamos convertir a PDF...")
                            # Aquí necesitaríamos wkhtmltopdf, pero no podemos acceder directamente

                    except Exception as e:
                        print(f"Error obteniendo HTML: {e}")

            except Exception as e:
                print(f"Error método 4: {e}")

            # Si llegamos aquí, ningún método funcionó
            print("No se pudo generar el PDF con ningún método disponible en Odoo 15")
            print("Verifica que:")
            print("1. El módulo 'account' esté instalado")
            print("2. Los reportes PDF estén configurados correctamente")
            print("3. wkhtmltopdf esté instalado en el servidor Odoo")

            return None

        except Exception as e:
            print(f"Error general obteniendo PDF de factura: {e}")
            return None

    def debug_available_methods(self):
        """Método para debuggear qué métodos están disponibles en ir.actions.report"""
        methods_to_test = [
            '_generate_pdf',
            '_render_template',
            '_render_qweb_html',
            '_render_qweb_pdf',
            'render_qweb_pdf',
            '_render',
            'sudo'
        ]

        print("Métodos disponibles en ir.actions.report:")
        for method in methods_to_test:
            try:
                # Solo intentar llamar métodos que no requieren parámetros específicos
                if method == 'sudo':
                    result = self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'ir.actions.report', 'sudo', []
                    )
                    print(f"✓ {method} - disponible")
                else:
                    # Para otros métodos, solo verificamos si existen sin ejecutarlos completamente
                    print(f"? {method} - verificando...")
            except Exception as e:
                if "has no attribute" in str(e):
                    print(f"✗ {method} - NO disponible")
                else:
                    print(f"✓ {method} - disponible pero falló en ejecución: {str(e)[:50]}...")

    def debug_invoice_reports(self):
        """Debuggear reportes específicos de facturas"""
        try:
            reports = self.models.execute_kw(
                self.db, self.uid, self.password,
                'ir.actions.report', 'search_read',
                [[('model', '=', 'account.move')]],
                {'fields': ['id', 'name', 'report_name', 'report_type', 'print_report_name']}
            )

            print(f"\nReportes disponibles para account.move ({len(reports)} encontrados):")
            for report in reports:
                print(f"ID: {report.get('id')}")
                print(f"  Nombre: {report.get('name')}")
                print(f"  Report Name: {report.get('report_name')}")
                print(f"  Tipo: {report.get('report_type')}")
                print(f"  Print Name: {report.get('print_report_name')}")
                print("  ---")

        except Exception as e:
            print(f"Error obteniendo reportes: {e}")

    def debug_available_reports(self):
        """Método para debuggear qué reportes están disponibles para account.move"""
        try:
            # Buscar todos los reportes para account.move
            reports = self.models.execute_kw(
                self.db, self.uid, self.password,
                'ir.actions.report', 'search_read',
                [[('model', '=', 'account.move')]],
                {'fields': ['name', 'report_name', 'report_type']}
            )

            print("Reportes disponibles para account.move:")
            for report in reports:
                print(f"  - Nombre: {report.get('name')}")
                print(f"    Report Name: {report.get('report_name')}")
                print(f"    Tipo: {report.get('report_type')}")
                print("  ---")

            return reports

        except Exception as e:
            print(f"Error obteniendo reportes: {e}")
            return []

    # También puedes verificar qué métodos están disponibles en ir.actions.report
    def debug_report_methods(self):
        """Verificar métodos disponibles en ir.actions.report"""
        try:
            # Esto no funcionará directamente via XML-RPC, pero puedes intentar
            # algunos métodos conocidos para ver cuáles existen
            methods_to_test = [
                '_render_qweb_pdf',
                'render_qweb_pdf',
                '_render',
                'generate_report',
                '_get_report_from_name'
            ]

            for method in methods_to_test:
                try:
                    # Intentar obtener información del método (esto podría fallar)
                    result = self.models.execute_kw(
                        self.db, self.uid, self.password,
                        'ir.actions.report', method,
                        ['account.report_invoice_with_payments', [1]]  # IDs de prueba
                    )
                    print(f"Método {method} existe y devolvió: {type(result)}")
                except Exception as e:
                    if "has no attribute" in str(e):
                        print(f"Método {method} NO existe")
                    else:
                        print(f"Método {method} existe pero falló: {str(e)[:100]}...")

        except Exception as e:
            print(f"Error general: {e}")
