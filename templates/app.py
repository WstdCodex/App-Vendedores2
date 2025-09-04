# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from odoo_connection import OdooConnection
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'  # Cambiar por una clave segura

# Configuración de Odoo - Ajustar según tu instalación
ODOO_CONFIG = {
    'url': 'http://localhost:8069',  # URL de tu servidor Odoo
    'db': 'nombre_de_tu_base_de_datos',  # Nombre de tu base de datos Odoo
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

@app.route('/mis-facturas')
def mis_facturas():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'], 
                             session['username'], session['password'])
        
        # Obtener facturas del vendedor
        facturas = odoo.get_vendedor_facturas(session['user_id'])
        
        return render_template('mis_facturas.html', facturas=facturas)
    except Exception as e:
        flash(f'Error al cargar facturas: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/clientes')
def clientes():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'], 
                             session['username'], session['password'])
        
        # Obtener clientes y sus facturas
        clientes_data = odoo.get_clientes_facturas(session['user_id'])
        
        return render_template('clientes.html', clientes=clientes_data)
    except Exception as e:
        flash(f'Error al cargar clientes: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/buscar-facturas')
def buscar_facturas():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    
    codigo_factura = request.args.get('codigo', '')
    estado_filtro = request.args.get('estado', '')
    
    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'], 
                             session['username'], session['password'])
        
        facturas = odoo.buscar_facturas(session['user_id'], codigo_factura, estado_filtro)
        return jsonify(facturas)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/buscar-clientes')
def buscar_clientes():
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    
    nombre_cliente = request.args.get('nombre', '')
    codigo_factura = request.args.get('factura', '')
    estado_filtro = request.args.get('estado', '')
    
    try:
        odoo = OdooConnection(ODOO_CONFIG['url'], ODOO_CONFIG['db'], 
                             session['username'], session['password'])
        
        clientes = odoo.buscar_clientes(session['user_id'], nombre_cliente, 
                                       codigo_factura, estado_filtro)
        return jsonify(clientes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)