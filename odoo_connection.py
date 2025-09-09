# odoo_connection.py
import xmlrpc.client
from datetime import datetime, date
from calendar import monthrange
import json

class OdooConnection:
    def __init__(self, url, db, username, password):
        self.url = url
        self.db = db
        self.username = username
        self.password = password
        self.uid = None

        # Conexiones XML-RPC con allow_none para soportar valores None
        self.common = xmlrpc.client.ServerProxy(
            f'{url}/xmlrpc/2/common', allow_none=True
        )
        self.models = xmlrpc.client.ServerProxy(
            f'{url}/xmlrpc/2/object', allow_none=True
        )

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

    def _clean_description(self, text):
        """Remove text starting from 'Marcas' onwards."""
        if not isinstance(text, str):
            return text
        idx = text.find('Marcas')
        if idx != -1:
            return text[:idx].strip()
        return text

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
                        'descripcion': self._clean_description(l.get('name', '')),
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
        """Obtener el PDF de una factura - Versión robusta para Odoo 15"""
        try:
            # Evitar action_invoice_print que está causando problemas
            # Buscar directamente el reporte de facturas

            # Método 1: Buscar reportes específicos de facturas
            try:
                reports = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'ir.actions.report', 'search_read',
                    [[
                        ('model', '=', 'account.move'),
                        ('report_type', '=', 'qweb-pdf')
                    ]],
                    {
                        'fields': ['id', 'report_name', 'name', 'print_report_name'],
                        'order': 'id asc'
                    }
                )

                if reports:
                    # Usar el primer reporte encontrado
                    report = reports[0]
                    report_id = report['id']
                    report_name = report['report_name']

                    print(f"Usando reporte - ID: {report_id}, Nombre: {report_name}")

                    # Construir URL simple y directa
                    base_url = self.url.rstrip('/')

                    # Diferentes formatos de URL que pueden funcionar
                    possible_urls = [
                        f"{base_url}/report/pdf/{report_name}/{factura_id}",
                        f"{base_url}/web/content?model=ir.actions.report&id={report_id}&filename={factura_id}.pdf&field=&download=true&data={factura_id}",
                        f"{base_url}/report/download/pdf/{report_id}/{factura_id}"
                    ]

                    return {
                        'report_id': report_id,
                        'report_name': report_name,
                        'urls': possible_urls,
                        'primary_url': possible_urls[0],
                        'method': 'direct_search'
                    }

            except Exception as e:
                print(f"Error buscando reportes: {e}")

            # Método 2: URLs basadas en convenciones conocidas de Odoo 15
            base_url = self.url.rstrip('/')

            # Reportes comunes en Odoo 15
            common_reports = [
                'account.report_invoice_with_payments',
                'account.report_invoice',
                'account.account_invoices'
            ]

            urls_by_report = {}
            for report_name in common_reports:
                urls_by_report[report_name] = [
                    f"{base_url}/report/pdf/{report_name}/{factura_id}",
                    f"{base_url}/report/html/{report_name}/{factura_id}"
                ]

            return {
                'method': 'conventional_urls',
                'urls_by_report': urls_by_report,
                'recommended_url': f"{base_url}/report/pdf/account.report_invoice_with_payments/{factura_id}"
            }

        except Exception as e:
            print(f"Error general obteniendo PDF: {e}")
            return None

    def get_simple_pdf_url(self, factura_id):
        """Método simple que devuelve la URL más probable del PDF"""
        base_url = self.url.rstrip('/')
        return f"{base_url}/report/pdf/account.report_invoice_with_payments/{factura_id}"

    def download_invoice_pdf(self, factura_id, username=None, password=None):
        """Descargar el PDF de una factura directamente desde Odoo.

        Intenta primero utilizar el servicio de reportes de Odoo vía
        XML-RPC; si falla, utiliza un método basado en sesión HTTP como
        respaldo.
        """

        import base64
        import xmlrpc.client


        login_user = username or self.username
        login_pass = password or self.password

        try:
            uid = self.uid
            models = self.models
            if username or password:
                common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
                uid = common.authenticate(self.db, login_user, login_pass, {})
                if not uid:
                    return None
                models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

            report_names = [
                'account.report_invoice_with_payments',
                'account.report_invoice'
            ]


            for report_name in report_names:
                try:
                    pdf_res = models.execute_kw(
                        self.db,
                        uid,
                        login_pass,
                        'ir.actions.report',
                        'render_qweb_pdf',
                        [report_name, [factura_id]]
                    )
                    pdf_content = pdf_res[0]
                    if isinstance(pdf_content, str):
                        pdf_content = base64.b64decode(pdf_content)
                    return pdf_content
                except Exception:
                    continue
        except Exception as e:
            print(f"Error con render_qweb_pdf: {e}")

        return self.download_pdf_with_session(
            factura_id,
            username=login_user,
            password=login_pass
        )

    def download_pdf_with_session(self, factura_id, username=None, password=None):
        """Descargar PDF usando sesión HTTP directa"""
        try:
            import requests

            # Usar credenciales de la conexión si no se proporcionan otras
            login_user = username or self.username
            login_pass = password or self.password
 
            session = requests.Session()
            base_url = self.url.rstrip('/')

            # Método 1: Intentar con autenticación básica HTTP
            try:
                pdf_url = self.get_simple_pdf_url(factura_id)
                response = session.get(
                    pdf_url,
                    auth=requests.auth.HTTPBasicAuth(login_user, login_pass),
                    timeout=30
                )

                if response.status_code == 200 and response.headers.get('content-type', '').startswith('application/pdf'):
                    return response.content
                else:
                    print(f"Error con auth básica: {response.status_code}")

            except Exception as e:
                print(f"Error con autenticación básica: {e}")

            # Método 2: Login web tradicional
            try:
                login_url = f"{base_url}/web/login"
                login_data = {
                    'login': login_user,
                    'password': login_pass,
                    'db': self.db
                }

                # Hacer POST al login
                login_response = session.post(login_url, data=login_data, allow_redirects=True)

                if login_response.status_code == 200:
                    # Verificar si el login fue exitoso (no hay forma perfecta, pero podemos intentar)
                    if 'web/login' not in login_response.url:
                        # Login exitoso, ahora descargar PDF
                        pdf_url = self.get_simple_pdf_url(factura_id)
                        pdf_response = session.get(pdf_url)

                        if pdf_response.status_code == 200:
                            content_type = pdf_response.headers.get('content-type', '')
                            if 'application/pdf' in content_type:
                                return pdf_response.content
                            else:
                                print(f"Respuesta no es PDF: {content_type}")
                                return None
                        else:
                            print(f"Error descargando PDF: {pdf_response.status_code}")
                            return None
                    else:
                        print("Login web falló - redirigido de vuelta al login")
                        return None
                else:
                    print(f"Error en login web: {login_response.status_code}")
                    return None

            except Exception as e:
                print(f"Error con login web: {e}")
                return None

            return None

        except ImportError:
            print("Necesitas instalar 'requests': pip install requests")
            return None
        except Exception as e:
            print(f"Error descargando PDF con sesión: {e}")
            return None



    def get_factura_pdf_info(self, factura_id):
        """Obtener información completa para descargar PDF"""
        try:
            # Verificar que la factura existe
            factura = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [factura_id], {'fields': ['name', 'state', 'move_type']}
            )

            if not factura:
                return {'error': 'Factura no encontrada'}

            factura_data = factura[0]
            if factura_data.get('move_type') != 'out_invoice':
                return {'error': 'El documento no es una factura de venta'}

            # Obtener URLs posibles
            pdf_info = self.get_factura_pdf(factura_id)

            if not pdf_info:
                return {'error': 'No se pudo obtener información del reporte'}

            # Intentar descarga automática
            pdf_content = self.download_pdf_with_session(factura_id)

            result = {
                'factura_id': factura_id,
                'factura_name': factura_data.get('name'),
                'factura_state': factura_data.get('state'),
                'pdf_info': pdf_info,
                'download_attempted': pdf_content is not None
            }

            if pdf_content:
                result['pdf_content'] = pdf_content
                result['status'] = 'success'
            else:
                result['status'] = 'manual_download_required'
                result['instructions'] = [
                    '1. Abre tu navegador e inicia sesión en Odoo',
                    f'2. Ve a la URL: {pdf_info.get("primary_url") or pdf_info.get("recommended_url")}',
                    '3. El PDF se descargará automáticamente'
                ]

            return result

        except Exception as e:
            return {'error': f'Error obteniendo información del PDF: {e}'}

    # Método de uso simple y directo
    def get_pdf_download_info(self, factura_id):
        """Método simple para obtener info de descarga"""
        url = self.get_simple_pdf_url(factura_id)
        return {
            'pdf_url': url,
            'instructions': f'Para descargar el PDF, abre esta URL en tu navegador (logueado en Odoo): {url}'
        }
