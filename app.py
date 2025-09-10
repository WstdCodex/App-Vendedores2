# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from odoo_connection import OdooConnection
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'  # Cambiar por una clave segura


def format_currency(value):
    """Format numbers with thousands separators and comma decimals."""
    try:
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return value


app.jinja_env.filters['format_currency'] = format_currency

# Configuración de Odoo - Ajustar según tu instalación
ODOO_CONFIG = {
    'url': 'https://wstd.ar',  # URL de tu servidor Odoo
    'db': 'odoo',  # Nombre de tu base de datos Odoo
    # Credenciales usadas para descargar/compartir PDFs de facturas
    'report_user': 'lucas@wstandard.com.ar',
    'report_password': 'lks.1822.95',
}

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'], username, password)
            user_info = odoo.authenticate()
            
            if user_info:
                session['user_id'] = user_info['user_id']
                session['username'] = username
                session['password'] = password
                session['user_name'] = user_info.get('name', username)
                flash('Inicio de sesión exitoso', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Credenciales incorrectas', 'error')
        except Exception as e:
            flash(f'Error de conexión: {str(e)}', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    return render_template('dashboard.html', user_name=session.get('user_name', 'Usuario'))


@app.route('/estadistico')
def estadistico():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    mes = request.args.get('mes')
    provincia_id = request.args.get('provincia_id', type=int)
    ciudad = request.args.get('ciudad', '')
    vendedor_id = request.args.get('vendedor_id', type=int)
    company_id = request.args.get('company_id', type=int)

    try:
        if mes:
            year, month = map(int, mes.split('-'))
        else:
            now = datetime.now()
            year, month = now.year, now.month
    except ValueError:
        now = datetime.now()
        year, month = now.year, now.month

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        mostrar_todo = (
            odoo.has_group('sales_team.group_sale_manager') or
            odoo.has_group('sales_team.group_sale_salesman_all_leads')
        )

        companias = odoo.get_companias() if mostrar_todo else []

        if mostrar_todo:
            vendedores = odoo.get_vendedores_especificos()
            user_id_param = vendedor_id if vendedor_id else None
        else:
            vendedores = []
            user_id_param = session['user_id']

        total_general = odoo.get_total_gastos_mes(
            user_id_param, year, month, company_id
        )

        provincias = odoo.get_provincias()
        ciudades = []
        if provincia_id:
            ciudades = odoo.get_ciudades(
                state_id=provincia_id,
                user_id=user_id_param,
                company_id=company_id,
            )

        clientes, total_filtrado = odoo.get_clientes_por_ubicacion_mes(
            year, month, provincia_id=provincia_id, ciudad=ciudad,
            user_id=user_id_param, company_id=company_id
        )
    except Exception as e:
        flash(f'Error al cargar estadísticas: {str(e)}', 'error')
        total_general = None
        provincias, ciudades, vendedores, companias = [], [], [], []
        clientes, total_filtrado = [], 0.0
        mostrar_todo = False

    selected_month = f"{year:04d}-{month:02d}"
    total = total_filtrado if (provincia_id or ciudad) else total_general
    return render_template(
        'estadistico.html',
        total=total,
        mes=selected_month,
        provincias=provincias,
        ciudades=ciudades,
        provincia_id=provincia_id,
        ciudad=ciudad,
        clientes=clientes,
        total_filtrado=total_filtrado,
        mostrar_todo=mostrar_todo,
        vendedores=vendedores,
        vendedor_id=vendedor_id,
        companias=companias,
        company_id=company_id,
    )

@app.route('/clientes')
def clientes():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        mostrar_todo = (
            odoo.has_group('sales_team.group_sale_manager') or
            odoo.has_group('sales_team.group_sale_salesman_all_leads')
        )
        companias = odoo.get_companias() if mostrar_todo else []
    except Exception:
        mostrar_todo = False
        companias = []
    # La lista de clientes se cargará mediante una solicitud asíncrona
    # para evitar demoras al cargar la página inicial.
    return render_template('clientes.html', clientes=[], mostrar_todo=mostrar_todo,
                           companias=companias)

@app.route('/clientes/<int:cliente_id>')
def cliente_detalle(cliente_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    mes_param = request.args.get('mes')
    return_url = request.args.get('return_url')
    company_id = request.args.get('company_id', type=int)

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']

        cliente_info = odoo.get_cliente(cliente_id, company_id=company_id)

        if mes_param:
            try:
                year, month = map(int, mes_param.split('-'))
                facturas = odoo.get_facturas_cliente_mes(cliente_id, year, month)
            except ValueError:
                # Si el parámetro es inválido, se muestran todas las facturas
                facturas = odoo.get_facturas_cliente(cliente_id)
                now = datetime.now()
                year, month = now.year, now.month
                mes_param = ''
        else:
            facturas = odoo.get_facturas_cliente(cliente_id)
            now = datetime.now()
            year, month = now.year, now.month

        total_gastado = odoo.get_total_gasto_cliente(cliente_id, company_id=company_id)

        return render_template('cliente_detalle.html', cliente=cliente_info,
                               facturas=facturas, total_gastado=total_gastado,
                               mes=mes_param or '', return_url=return_url)
    except Exception as e:
        flash(f'Error al cargar cliente: {str(e)}', 'error')
        if return_url:
            return redirect(return_url)
        return redirect(url_for('clientes'))

@app.route('/clientes/<int:cliente_id>/factura/<int:factura_id>')
def factura_detalle(cliente_id, factura_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']

        factura = odoo.get_factura(factura_id)
        if not factura:
            flash('Factura no encontrada', 'error')
            return redirect(url_for('cliente_detalle', cliente_id=cliente_id))

        return render_template('factura_detalle.html', factura=factura, cliente_id=cliente_id)
    except Exception as e:
        flash(f'Error al cargar factura: {str(e)}', 'error')
        return redirect(url_for('cliente_detalle', cliente_id=cliente_id))

@app.route('/facturas/<int:factura_id>/pdf')
def descargar_factura_pdf(factura_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        factura = odoo.get_factura(factura_id)
        filename = factura.get('nombre', f'factura_{factura_id}') if factura else f'factura_{factura_id}'

        pdf_content = odoo.download_invoice_pdf(
            factura_id,
            username=ODOO_CONFIG['report_user'],
            password=ODOO_CONFIG['report_password']
        )
        if pdf_content:
            response = Response(pdf_content, mimetype='application/pdf')
            response.headers['Content-Disposition'] = (
                f'attachment; filename={filename}.pdf'
            )
            return response

        if not factura:
            flash('No se pudo obtener la información de la factura', 'error')
            return redirect(request.referrer or url_for('dashboard'))

        # Si no se pudo obtener el PDF desde Odoo, generamos uno simple.
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # Dibujar el logo en la esquina superior izquierda

        logo_path = os.path.join(app.root_path, 'static', 'standard_logo.png')

        logo_w, logo_h = 120, 40
        try:
            p.drawImage(logo_path, 40, height - logo_h - 40,
                        width=logo_w, height=logo_h, mask='auto')
        except Exception:
            pass

        y = height - logo_h - 60
        p.setFont('Helvetica-Bold', 14)
        p.drawString(50, y, f"Factura: {factura['nombre']}")
        y -= 20
        p.setFont('Helvetica', 12)
        p.drawString(50, y, f"Fecha: {factura['fecha']}")
        y -= 20
        p.drawString(50, y, f"Cliente: {factura['cliente']}")
        y -= 30
        # Encabezados de la tabla
        def draw_headers(y_pos):
            p.setFont('Helvetica-Bold', 12)
            p.drawString(50, y_pos, 'Descripción')
            p.drawString(250, y_pos, 'Cantidad')
            p.drawString(320, y_pos, 'P.Unit')
            p.drawString(390, y_pos, 'IVA 21%')
            p.drawString(460, y_pos, 'Total')
            y_line = y_pos - 5
            p.line(50, y_line, 560, y_line)
            return y_line - 10

        y = draw_headers(y)
        p.setFont('Helvetica', 10)
        for line in factura.get('lineas', []):
            p.drawString(50, y, str(line['descripcion'])[:35])
            p.drawRightString(290, y, str(line['cantidad']))
            p.drawRightString(360, y, f"{line['precio_unitario']:.2f}")
            p.drawRightString(430, y, f"{line['iva']:.2f}")
            p.drawRightString(510, y, f"{line['total']:.2f}")
            y -= 15
            if y < 100:
                p.showPage()
                y = height - 50
                y = draw_headers(y)
                p.setFont('Helvetica', 10)

        y -= 20
        p.setFont('Helvetica', 12)
        p.drawString(50, y, f"Importe libre de impuestos: ${factura['importe_untaxed']:.2f}")
        y -= 15
        p.drawString(50, y, f"IVA 21%: ${factura['iva_21']:.2f}")
        y -= 15
        p.drawString(50, y, f"Perc IIBB ARBA: ${factura['perc_iibb_arba']:.2f}")
        y -= 15
        p.drawString(50, y, f"Total con impuestos: ${factura['total']:.2f}")
        y -= 15
        p.drawString(50, y, f"Importe adeudado: ${factura['amount_residual']:.2f}")
        y -= 15
        if factura.get('cae'):
            p.drawString(50, y, f"CAE: {factura['cae']}")
            y -= 15
        if factura.get('cae_due_date'):
            p.drawString(50, y, f"Vencimiento CAE: {factura['cae_due_date']}")
        p.showPage()
        p.save()
        buffer.seek(0)

        response = Response(buffer.getvalue(), mimetype='application/pdf')
        response.headers['Content-Disposition'] = (
            f'attachment; filename=factura_{factura_id}.pdf'
        )
        return response
    except Exception as e:
        flash(f'Error al descargar factura: {str(e)}', 'error')
        return redirect(request.referrer or url_for('dashboard'))


@app.route('/api/buscar-facturas')
def buscar_facturas():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    
    codigo_factura = request.args.get('codigo', '')
    estado_filtro = request.args.get('estado', '')
    
    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        
        facturas = odoo.buscar_facturas(session['user_id'], codigo_factura, estado_filtro)
        return jsonify(facturas)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provincias')
def api_provincias():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        provincias = odoo.get_provincias()
        return jsonify(provincias)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vendedores')
def api_vendedores():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        mostrar_todo = (
            odoo.has_group('sales_team.group_sale_manager') or
            odoo.has_group('sales_team.group_sale_salesman_all_leads')
        )
        if not mostrar_todo:
            return jsonify([])
        vendedores = odoo.get_vendedores_especificos()
        return jsonify(vendedores)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ciudades')
def api_ciudades():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    provincia_id = request.args.get('provincia_id', type=int)
    vendedor_id = request.args.get('vendedor_id', type=int)
    company_id = request.args.get('company_id', type=int)

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        mostrar_todo = (
            odoo.has_group('sales_team.group_sale_manager') or
            odoo.has_group('sales_team.group_sale_salesman_all_leads')
        )
        user_id_param = None if mostrar_todo else session['user_id']
        if mostrar_todo and vendedor_id:
            user_id_param = vendedor_id
        ciudades = odoo.get_ciudades(
            state_id=provincia_id,
            user_id=user_id_param,
            company_id=company_id,
        )
        return jsonify(ciudades)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/buscar-clientes')
def api_buscar_clientes():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    nombre_cliente = request.args.get('nombre', '')
    limite = request.args.get('limite', 20)
    provincia_id = request.args.get('provincia_id', type=int)
    ciudad = request.args.get('ciudad', '')
    vendedor_id = request.args.get('vendedor_id', type=int)
    adeudados = request.args.get('adeudados')
    company_id = request.args.get('company_id', type=int)

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        mostrar_todo = (
            odoo.has_group('sales_team.group_sale_manager') or
            odoo.has_group('sales_team.group_sale_salesman_all_leads')
        )

        user_id_param = None if mostrar_todo else session['user_id']
        if mostrar_todo and vendedor_id:
            user_id_param = vendedor_id
        clientes = odoo.buscar_clientes(
            nombre_cliente,
            user_id=user_id_param,
            limit=int(limite),
            provincia_id=provincia_id,
            ciudad=ciudad,
            company_id=company_id,
        )
        if adeudados:
            clientes = [c for c in clientes if c.get('deuda_total', 0) > 0]
        clientes.sort(key=lambda c: c.get('deuda_total', 0), reverse=True)
        return jsonify(clientes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cliente/<int:cliente_id>/facturas')
def api_facturas_cliente(cliente_id):
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    codigo_factura = request.args.get('codigo', '')
    estado_filtro = request.args.get('estado', '')
    mes = request.args.get('mes')

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        if mes:
            try:
                year, month = map(int, mes.split('-'))
                facturas = odoo.get_facturas_cliente_mes(
                    cliente_id, year, month, codigo_factura, estado_filtro
                )
            except ValueError:
                facturas = odoo.get_facturas_cliente(
                    cliente_id, codigo_factura, estado_filtro
                )
        else:
            facturas = odoo.get_facturas_cliente(
                cliente_id, codigo_factura, estado_filtro
            )
        return jsonify(facturas)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
