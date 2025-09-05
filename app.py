# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from odoo_connection import OdooConnection

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'  # Cambiar por una clave segura

# Configuración de Odoo - Ajustar según tu instalación
ODOO_CONFIG = {
    'url': 'https://wstd.ar',  # URL de tu servidor Odoo
    'db': 'odoo',  # Nombre de tu base de datos Odoo
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

@app.route('/clientes')
def clientes():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # La lista de clientes se cargará mediante una solicitud asíncrona
    # para evitar demoras al cargar la página inicial.
    return render_template('clientes.html', clientes=[])

@app.route('/clientes/<int:cliente_id>')
def cliente_detalle(cliente_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']

        cliente_info = odoo.get_cliente(cliente_id)
        facturas = odoo.get_facturas_cliente(cliente_id)

        return render_template('cliente_detalle.html', cliente=cliente_info, facturas=facturas)
    except Exception as e:
        flash(f'Error al cargar cliente: {str(e)}', 'error')
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

        pdf_content = odoo.get_factura_pdf(factura_id)
        if pdf_content:
            response = Response(pdf_content, mimetype='application/pdf')
            response.headers['Content-Disposition'] = (
                f'attachment; filename=factura_{factura_id}.pdf'
            )
            return response

        # Si no se pudo generar el PDF, devolvemos la factura en texto plano.
        factura = odoo.get_factura(factura_id)
        if not factura:
            flash('No se pudo obtener la información de la factura', 'error')
            return redirect(request.referrer or url_for('dashboard'))

        lines = [
            f"Descripción: {l['descripcion']} - Cantidad: {l['cantidad']} - Precio: {l['precio_unitario']} - Subtotal: {l['subtotal']}"
            for l in factura.get('lineas', [])
        ]
        text_content = (
            f"Factura: {factura['nombre']}\n"
            f"Fecha: {factura['fecha']}\n"
            f"Cliente: {factura['cliente']}\n"
            f"Total: {factura['total']}\n\n"
            + "\n".join(lines)
        )

        response = Response(text_content, mimetype='text/plain')
        response.headers['Content-Disposition'] = (
            f'attachment; filename=factura_{factura_id}.txt'
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

@app.route('/api/ciudades')
def api_ciudades():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    provincia_id = request.args.get('provincia_id', type=int)

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']
        ciudades = odoo.get_ciudades(state_id=provincia_id, user_id=session['user_id'])
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

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']

        clientes = odoo.buscar_clientes(
            nombre_cliente,
            user_id=session['user_id'],
            limit=int(limite),
            provincia_id=provincia_id,
            ciudad=ciudad
        )
        return jsonify(clientes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cliente/<int:cliente_id>/facturas')
def api_facturas_cliente(cliente_id):
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    codigo_factura = request.args.get('codigo', '')
    estado_filtro = request.args.get('estado', '')

    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'],
                              session['username'], session['password'])
        odoo.uid = session['user_id']

        facturas = odoo.get_facturas_cliente(cliente_id, codigo_factura, estado_filtro)
        return jsonify(facturas)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
