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

    def get_companias(self):
        """Obtener compañías específicas disponibles en Odoo."""
        try:
            nombres = [
                'W.STANDARD ARGENTINA',
                'W.STANDARD GROUP SRL',
                'BARDELLI GUALTERIO LUIS JUAN',
            ]
            companias = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.company',
                'search_read',
                [[('name', 'in', nombres)]],
                {'fields': ['name']},
            )
            return [{'id': c['id'], 'nombre': c['name']} for c in companias]
        except Exception as e:
            print(f"Error obteniendo compañías: {e}")
            return []

    def get_total_gastos_mes(self, user_id, year, month, company_id=None):
        """Obtener el total efectivamente pagado en un mes específico.

        Si ``user_id`` es ``None`` se calcula el total de todos los
        vendedores; en caso contrario solo del vendedor indicado. Solo se
        consideran los montos ya abonados, descartando lo que aún está
        pendiente de pago.
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
            if company_id is not None:
                domain.append(('company_id', '=', company_id))
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search', [domain]
            )
            if not facturas_ids:
                return 0.0
            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [facturas_ids], {'fields': ['amount_total', 'amount_residual']}
            )
            total = 0.0
            for f in facturas:
                monto = f.get('amount_total', 0.0) or 0.0
                pendiente = f.get('amount_residual', 0.0) or 0.0
                pagado = monto - pendiente
                if pagado < 0:
                    pagado = 0.0
                total += pagado
            return total
        except Exception as e:
            print(f"Error obteniendo total mensual: {e}")
            return 0.0

    def get_total_gasto_cliente_mes(self, partner_id, year, month):
        """Obtener el total pagado por un cliente en un mes específico.

        Incluye los montos abonados de manera parcial en cada factura.
        """
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
                [facturas_ids], {'fields': ['amount_total', 'amount_residual']}

            )
            total = 0.0
            for f in facturas:
                monto = f.get('amount_total', 0.0) or 0.0
                pendiente = f.get('amount_residual', 0.0) or 0.0
                pagado = monto - pendiente
                if pagado < 0:
                    pagado = 0.0
                total += pagado
            return total
        except Exception as e:
            print(f"Error obteniendo gasto total del cliente: {e}")
            return 0.0

    def get_total_gasto_cliente(self, partner_id, company_id=None):
        """Obtener el total efectivamente abonado por un cliente.

        Calcula el total pagado a partir de las facturas del cliente
        tomando ``amount_total - amount_residual`` para cada factura en
        estado ``posted``. Este método evita consultar el modelo
        ``account.payment``, que puede estar restringido para usuarios
        comerciales.
        """
        try:
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('partner_id', '=', partner_id),
                ('state', '=', 'posted'),
            ]
            if company_id is not None:
                domain.append(('company_id', '=', company_id))
            facturas_ids = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search', [domain]
            )
            if not facturas_ids:
                return 0.0
            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [facturas_ids], {'fields': ['amount_total', 'amount_residual']}
            )
            total = 0.0
            for f in facturas:
                monto = f.get('amount_total', 0.0) or 0.0
                pendiente = f.get('amount_residual', 0.0) or 0.0
                pagado = monto - pendiente
                if pagado < 0:
                    pagado = 0.0
                total += pagado
            return total
        except Exception as e:
            print(f"Error obteniendo gasto total del cliente: {e}")
            return 0.0

    def get_clientes_por_ubicacion_mes(self, year, month, provincia_id=None,
                                       ciudad='', user_id=None, company_id=None):
        """Obtener clientes de una ubicación y su gasto mensual pagado.

        Parameters
        ----------
        year, month : int
            Periodo a consultar.
        provincia_id : int, optional
            ID de la provincia (``state_id``).
        ciudad : str, optional
            Nombre de la ciudad.
        user_id : int, optional
            Filtrar por vendedor. Si es ``None`` se incluyen todos los
            vendedores.

        Returns
        -------
        list[dict], float
            Lista de clientes con el total gastado y el total acumulado.
        """
        try:
            domain = [
                ('customer_rank', '>', 0),
                ('parent_id', '=', False),
            ]
            if user_id is not None:
                domain.append(('user_id', '=', user_id))
            if provincia_id:
                domain.append(('state_id', '=', provincia_id))
            if ciudad:
                domain.append(('city', 'ilike', ciudad))

            partners = self.models.execute_kw(
                self.db, self.uid, self.password,
                'res.partner', 'search_read', [domain],
                {'fields': ['name']}
            )

            if not partners:
                return [], 0.0

            partner_ids = [p['id'] for p in partners]
            start_date = datetime(year, month, 1).strftime('%Y-%m-%d')
            end_day = monthrange(year, month)[1]
            end_date = datetime(year, month, end_day).strftime('%Y-%m-%d')

            invoice_domain = [
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', start_date),
                ('invoice_date', '<=', end_date),
                ('partner_id', 'in', partner_ids),
            ]
            if company_id is not None:
                invoice_domain.append(('company_id', '=', company_id))
            if user_id is not None:
                invoice_domain.append(('invoice_user_id', '=', user_id))

            facturas = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'search_read', [invoice_domain],
                {'fields': ['partner_id', 'amount_total', 'amount_residual']}
            )

            totales = {}
            for f in facturas:
                partner = f.get('partner_id')
                if not partner:
                    continue
                partner_id = partner[0] if isinstance(partner, list) else partner
                monto = f.get('amount_total', 0.0) or 0.0
                pendiente = f.get('amount_residual', 0.0) or 0.0
                pagado = monto - pendiente
                if pagado < 0:
                    pagado = 0.0
                totales[partner_id] = totales.get(partner_id, 0.0) + pagado

            resultados = []
            total_general = 0.0
            for p in partners:
                total_cliente = totales.get(p['id'], 0.0)
                if total_cliente > 0:
                    resultados.append({
                        'id': p['id'],
                        'nombre': p['name'],
                        'total_mes': total_cliente,
                    })
                    total_general += total_cliente

            resultados.sort(key=lambda x: x['total_mes'], reverse=True)
            return resultados, total_general
        except Exception as e:
            print(f"Error obteniendo clientes por ubicación: {e}")
            return [], 0.0

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

    def get_ciudades(self, state_id=None, user_id=None, company_id=None):
        """Obtener lista de ciudades disponibles, filtradas opcionalmente por provincia, vendedor y compañía."""
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

    def get_vendedores_especificos(self):
        """Obtener información de vendedores específicos por nombre."""
        try:
            nombres = ['DE STEFANO RAFAEL GASTON', 'FERUGLIO LEANDRO EZEQUIEL']
            usuarios = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.users',
                'search_read',
                [[('name', 'in', nombres)]],
                {'fields': ['name']}
            )
            return [{'id': u['id'], 'nombre': u['name']} for u in usuarios]
        except Exception as e:
            print(f"Error obteniendo vendedores específicos: {e}")
            return []

    def buscar_clientes(self, nombre_cliente: str = '', user_id: int = None,
                         limit: int = 20, provincia_id: int = None,
                         ciudad: str = '', company_id: int = None):
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

            kwargs = {
                'fields': ['name', 'credit', 'debit', 'user_id'],
                'limit': limit,
            }
            if company_id is not None:
                kwargs['context'] = {
                    'force_company': company_id,
                    'allowed_company_ids': [company_id],
                }

            # Utilizamos ``search_read`` para obtener los datos de los clientes
            clientes = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.partner',
                'search_read',
                [domain],
                kwargs,
            )

            print(f"Clientes encontrados: {len(clientes) if clientes else 0}")

            if not clientes:
                return []

            clientes_formateados = []
            for c in clientes:
                cliente_user_id = c.get('user_id')
                if cliente_user_id:
                    cliente_user_id = (
                        cliente_user_id[0]
                        if isinstance(cliente_user_id, list)
                        else cliente_user_id
                    )

                # Si se solicita filtrar por vendedor y no coincide, lo saltamos
                if user_id is not None and cliente_user_id != user_id:
                    print(
                        f"Cliente {c.get('name')} tiene vendedor {cliente_user_id}, esperado {user_id}"
                    )
                    continue

                credito = c.get('credit', 0.0)
                debito = c.get('debit', 0.0)
                balance = debito - credito
                deuda_total = max(balance, 0.0)
                saldo_favor = max(-balance, 0.0)
                clientes_formateados.append(
                    {
                        'id': c['id'],
                        'nombre': c.get('name', ''),
                        'deuda_total': deuda_total,
                        'saldo_favor': saldo_favor,
                        'vendedor_id': cliente_user_id,
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

                credito = c.get('credit', 0.0)
                debito = c.get('debit', 0.0)
                balance = debito - credito
                deuda_total = max(balance, 0.0)
                saldo_favor = max(-balance, 0.0)

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

    def get_cliente(self, partner_id, company_id=None):
        """Obtener información del cliente"""
        try:
            kwargs = {
                'fields': ['name', 'email', 'phone', 'street', 'credit', 'debit', 'user_id']
            }
            if company_id is not None:

                kwargs['context'] = {
                    'force_company': company_id,
                    'allowed_company_ids': [company_id],
                }

            cliente = self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                'res.partner',
                'read',
                [partner_id],
                kwargs,
            )
            if cliente:
                c = cliente[0]
                credito = c.get('credit', 0.0)
                debito = c.get('debit', 0.0)
                balance = debito - credito
                deuda_total = max(balance, 0.0)
                saldo_favor = max(-balance, 0.0)
                
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

    def get_facturas_cliente_mes(self, partner_id, year, month,
                                 codigo_factura='', estado_filtro=''):
        """Obtener facturas publicadas de un cliente en un mes específico."""
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
            print(f"Error obteniendo facturas del cliente en el mes: {e}")
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
        """Descargar el PDF de una factura sin usar la ruta ``/report/pdf``.

        El método intenta, en orden:

        1. Buscar un adjunto PDF existente asociado a la factura.
        2. Generar el PDF mediante los reportes QWeb de Odoo usando XML-RPC.
        3. Forzar la generación del adjunto y devolverlo.

        Parameters
        ----------
        factura_id : int
            ID de la factura en Odoo.
        username, password : str, optional
            Credenciales alternativas para realizar la descarga.

        Returns
        -------
        bytes | None
            Contenido del PDF en bytes o ``None`` si no se pudo obtener.
        """

        login_user = username or self.username
        login_pass = password or self.password

        try:
            # 1) Buscar si ya existe un adjunto PDF de la factura
            pdf_content = self.get_invoice_attachment(factura_id)
            if pdf_content:
                return pdf_content

            # 2) Intentar generar el PDF directamente via XML-RPC
            pdf_content = self.download_invoice_pdf_direct(
                factura_id, username=login_user, password=login_pass
            )
            if pdf_content:
                return pdf_content

            # 3) Forzar la generación del adjunto y devolverlo
            pdf_content = self.force_generate_pdf_attachment(factura_id)
            return pdf_content

        except Exception as e:
            print(f"Error descargando PDF directamente: {e}")
            return None

    def download_pdf_with_session(self, factura_id, username=None, password=None):
        """Descargar PDF usando sesión HTTP directa - Versión mejorada para Odoo 15"""
        try:
            import requests
            from urllib.parse import urljoin

            login_user = username or self.username
            login_pass = password or self.password

            session = requests.Session()
            base_url = self.url.rstrip('/')

            # Configurar headers comunes
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'es-ES,es;q=0.8,en;q=0.6',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })

            print(f"Intentando login con usuario: {login_user} en DB: {self.db}")

            try:
                # Paso 1: Obtener la página de login para conseguir el CSRF token
                login_page_url = f"{base_url}/web/login"
                print(f"Obteniendo página de login: {login_page_url}")
                
                login_page = session.get(login_page_url, timeout=30)
                print(f"Status página de login: {login_page.status_code}")
                
                if login_page.status_code != 200:
                    print(f"Error obteniendo página de login: {login_page.status_code}")
                    return None

                # Buscar CSRF token en la página
                csrf_token = None
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(login_page.content, 'html.parser')
                    csrf_input = soup.find('input', {'name': 'csrf_token'})
                    if csrf_input:
                        csrf_token = csrf_input.get('value')
                        print(f"CSRF token encontrado: {csrf_token[:20]}..." if csrf_token else "No encontrado")
                except ImportError:
                    # Si BeautifulSoup no está disponible, intentar con regex
                    import re
                    csrf_match = re.search(r'name="csrf_token"[^>]*value="([^"]*)"', login_page.text)
                    if csrf_match:
                        csrf_token = csrf_match.group(1)
                        print(f"CSRF token encontrado con regex: {csrf_token[:20]}...")

                # Paso 2: Preparar datos de login
                login_data = {
                    'login': login_user,
                    'password': login_pass,
                    'db': self.db
                }
                
                # Agregar CSRF token si se encontró
                if csrf_token:
                    login_data['csrf_token'] = csrf_token

                print(f"Datos de login preparados: {list(login_data.keys())}")

                # Paso 3: Realizar el login
                login_response = session.post(
                    login_page_url, 
                    data=login_data, 
                    timeout=30,
                    allow_redirects=True
                )
                
                print(f"Status login: {login_response.status_code}")
                print(f"URL final después del login: {login_response.url}")

                # Verificar si el login fue exitoso
                if login_response.status_code != 200:
                    print(f"Error en login: Status {login_response.status_code}")
                    return None

                # Verificar que no fuimos redirigidos de vuelta al login
                if '/web/login' in login_response.url and 'error' in login_response.url.lower():
                    print("Login falló - redirigido de vuelta al login con error")
                    return None

                # Verificar que tenemos una sesión válida
                if 'session_id' not in session.cookies and 'frontend_lang' not in session.cookies:
                    print("No se estableció una sesión válida")
                    # Intentar buscar cookies de sesión con nombres alternativos
                    cookie_names = list(session.cookies.keys())
                    print(f"Cookies disponibles: {cookie_names}")

                print("Login web exitoso")

                # Paso 4: Intentar descargar el PDF
                pdf_urls = [
                    f"{base_url}/report/pdf/account.report_invoice_with_payments/{factura_id}",
                    f"{base_url}/report/pdf/account.report_invoice/{factura_id}",
                    f"{base_url}/report/pdf/account.account_invoices/{factura_id}"
                ]

                for pdf_url in pdf_urls:
                    print(f"Intentando descargar PDF desde: {pdf_url}")
                    
                    try:
                        pdf_response = session.get(pdf_url, timeout=60)
                        print(f"Status descarga PDF: {pdf_response.status_code}")
                        
                        if pdf_response.status_code == 200:
                            content_type = pdf_response.headers.get('content-type', '').lower()
                            print(f"Content-Type: {content_type}")
                            
                            if 'application/pdf' in content_type:
                                print(f"PDF descargado exitosamente, tamaño: {len(pdf_response.content)} bytes")
                                return pdf_response.content
                            elif 'text/html' in content_type:
                                # Si recibimos HTML, puede ser una página de error o login
                                if 'login' in pdf_response.text.lower():
                                    print("Recibimos página de login - sesión expirada")
                                    return None
                                else:
                                    print("Recibimos HTML en lugar de PDF")
                                    continue
                        elif pdf_response.status_code == 403:
                            print("Acceso denegado al PDF - verificar permisos")
                            continue
                        elif pdf_response.status_code == 404:
                            print("URL del PDF no encontrada")
                            continue
                        else:
                            print(f"Error descargando PDF: {pdf_response.status_code}")
                            continue
                            
                    except Exception as e:
                        print(f"Error en descarga de {pdf_url}: {e}")
                        continue

                print("No se pudo descargar el PDF desde ninguna URL")
                return None

            except Exception as e:
                print(f"Error en proceso de descarga: {e}")
                return None

        except ImportError:
            print("Necesitas instalar 'requests': pip install requests")
            return None
        except Exception as e:
            print(f"Error general descargando PDF: {e}")
            return None

    def get_invoice_attachment(self, factura_id):
        """Buscar un PDF existente en los adjuntos de la factura."""
        try:
            attachments = self.models.execute_kw(
                self.db, self.uid, self.password,
                'ir.attachment', 'search_read',
                [[
                    ('res_model', '=', 'account.move'),
                    ('res_id', '=', factura_id),
                    ('mimetype', '=', 'application/pdf')
                ]],
                {'fields': ['datas'], 'limit': 1}
            )
            if attachments:
                import base64
                data = attachments[0].get('datas')
                if data:
                    return base64.b64decode(data)
            return None
        except Exception as e:
            print(f"Error buscando adjunto PDF: {e}")
            return None

    def force_generate_pdf_attachment(self, factura_id):
        """Forzar la generación de un adjunto PDF de la factura."""
        try:
            try:
                self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'account.move', 'action_invoice_print', [[factura_id]]
                )
            except Exception as e:
                print(f"Error al forzar impresión de la factura: {e}")
            return self.get_invoice_attachment(factura_id)
        except Exception as e:
            print(f"Error generando adjunto PDF: {e}")
            return None

    def get_factura_pdf_info_improved(self, factura_id):
        """Versión mejorada para obtener información del PDF con múltiples estrategias"""
        try:
            # Verificar que la factura existe y es válida
            factura = self.models.execute_kw(
                self.db, self.uid, self.password,
                'account.move', 'read',
                [factura_id], {'fields': ['name', 'state', 'move_type']}
            )

            if not factura:
                return {'error': 'Factura no encontrada', 'status': 'error'}

            factura_data = factura[0]

            if factura_data.get('move_type') != 'out_invoice':
                return {'error': 'El documento no es una factura de venta', 'status': 'error'}

            if factura_data.get('state') not in ['posted']:
                return {'error': 'La factura debe estar confirmada para generar PDF', 'status': 'error'}

            print(f"Procesando factura {factura_data.get('name')} (ID: {factura_id})")

            pdf_content = None
            method_used = None

            # Estrategia 1: Buscar en adjuntos existentes
            print("=== Estrategia 1: Buscando adjuntos existentes ===")
            pdf_content = self.get_invoice_attachment(factura_id)
            if pdf_content:
                method_used = "attachment"

            # Estrategia 2: Render directo vía XML-RPC
            if not pdf_content:
                print("=== Estrategia 2: Render directo XML-RPC ===")
                pdf_content = self.download_invoice_pdf_direct(factura_id)
                if pdf_content:
                    method_used = "xmlrpc_direct"

            # Estrategia 3: Forzar generación y buscar adjunto
            if not pdf_content:
                print("=== Estrategia 3: Forzar generación ===")
                pdf_content = self.force_generate_pdf_attachment(factura_id)
                if pdf_content:
                    method_used = "forced_generation"

            # Estrategia 4: Descarga vía web (como último recurso)
            if not pdf_content:
                print("=== Estrategia 4: Descarga web ===")
                pdf_content = self.download_pdf_with_session(factura_id)
                if pdf_content:
                    method_used = "web_session"

            base_url = self.url.rstrip('/')
            primary_url = f"{base_url}/report/pdf/account.report_invoice_with_payments/{factura_id}"

            result = {
                'factura_id': factura_id,
                'factura_name': factura_data.get('name'),
                'factura_state': factura_data.get('state'),
                'pdf_url': primary_url,
                'method_used': method_used
            }

            if pdf_content:
                result.update({
                    'status': 'success',
                    'pdf_content': pdf_content,
                    'pdf_size': len(pdf_content),
                    'message': f'PDF obtenido exitosamente usando: {method_used}'
                })
            else:
                result.update({
                    'status': 'manual_download_required',
                    'message': 'Todas las estrategias automáticas fallaron. Usa el enlace manual.',
                    'manual_instructions': [
                        '1. Abre tu navegador e inicia sesión en Odoo',
                        f'2. Ve a la URL: {primary_url}',
                        '3. El PDF se descargará automáticamente'
                    ],
                    'alternative_urls': [
                        f"{base_url}/web/content?model=account.move&id={factura_id}&field=message_main_attachment_id&download=true",
                        f"{base_url}/web/report/pdf/account.report_invoice/{factura_id}"
                    ]
                })

            return result

        except Exception as e:
            print(f"Error obteniendo información del PDF: {e}")
            return {
                'error': f'Error interno: {e}',
                'status': 'error'
            }

    # Método alternativo usando render directo
    def download_invoice_pdf_direct(self, factura_id, username=None, password=None):
        """Método alternativo usando render directo de Odoo"""
        try:
            import base64
            
            login_user = username or self.username
            login_pass = password or self.password
            
            # Usar credenciales actuales o las proporcionadas
            uid = self.uid
            models = self.models
            
            # Si se proporcionan credenciales diferentes, hacer nueva autenticación
            if username or password:
                import xmlrpc.client
                common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
                uid = common.authenticate(self.db, login_user, login_pass, {})
                if not uid:
                    print("Error: No se pudo autenticar con las credenciales proporcionadas")
                    return None
                models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)

            # Lista de reportes a intentar en orden de preferencia
            report_names = [
                'account.report_invoice_with_payments',
                'account.report_invoice',
                'account.account_invoices',
                'account.report_invoice_document'
            ]

            for report_name in report_names:
                try:
                    print(f"Intentando generar PDF con reporte: {report_name}")
                    
                    # Método 1: render_qweb_pdf
                    try:
                        result = models.execute_kw(
                            self.db, uid, login_pass,
                            'ir.actions.report', 'render_qweb_pdf',
                            [report_name, [factura_id]]
                        )
                        
                        if result and len(result) >= 1:
                            pdf_content = result[0]
                            if isinstance(pdf_content, str):
                                pdf_content = base64.b64decode(pdf_content)
                            elif isinstance(pdf_content, bytes):
                                pass  # Ya está en bytes
                            else:
                                print(f"Tipo de contenido inesperado: {type(pdf_content)}")
                                continue
                                
                            print(f"PDF generado exitosamente con {report_name}, tamaño: {len(pdf_content)} bytes")
                            return pdf_content
                            
                    except Exception as e:
                        print(f"Error con render_qweb_pdf para {report_name}: {e}")

                    # Método 2: _render_qweb_pdf (método interno)
                    try:
                        result = models.execute_kw(
                            self.db, uid, login_pass,
                            'ir.actions.report', '_render_qweb_pdf',
                            [report_name, [factura_id]]
                        )
                        
                        if result and len(result) >= 1:
                            pdf_content = result[0]
                            if isinstance(pdf_content, str):
                                pdf_content = base64.b64decode(pdf_content)
                            print(f"PDF generado con _render_qweb_pdf, tamaño: {len(pdf_content)} bytes")
                            return pdf_content
                            
                    except Exception as e:
                        print(f"Error con _render_qweb_pdf para {report_name}: {e}")

                except Exception as e:
                    print(f"Error general con reporte {report_name}: {e}")
                    continue

            print("No se pudo generar PDF con ningún reporte")
            return None

        except Exception as e:
            print(f"Error en descarga directa: {e}")
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
