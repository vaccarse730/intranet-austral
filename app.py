import urllib.request
import json
import os
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta_para_sesiones'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

EXTENSIONES_IMAGEN = {'png', 'jpg', 'jpeg', 'gif'}

def es_imagen(filename):
    if '.' in filename:
        ext = filename.rsplit('.', 1)[1].lower()
        return ext in EXTENSIONES_IMAGEN
    return False

def init_db():
    conn = sqlite3.connect('intranet_nueva.db')
    cursor = conn.cursor()
    
    # 1. Tabla de Usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE,
            clave TEXT,
            puesto TEXT,
            cumpleanos TEXT
        )
    ''')
    
    # 2. Tabla de Mensajes del Muro
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            autor TEXT,
            contenido TEXT,
            es_foto INTEGER DEFAULT 0,
            puesto_autor TEXT,
            fecha TEXT
        )
    ''')
    
    # 3. Tabla de Likes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mensaje_id INTEGER,
            usuario TEXT,
            UNIQUE(mensaje_id, usuario)
        )
    ''')
    
    # 4. Tabla de Archivos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS archivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_archivo TEXT UNIQUE,
            subido_por TEXT,
            fecha TEXT,
            carpeta TEXT DEFAULT 'General'
        )
    ''')
    
    # 5. Tabla de Carpetas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS carpetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE,
            creador TEXT DEFAULT 'Sistema'
        )
    ''')
    
    # 6. Tabla del Directorio Telefónico
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS directorio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            telefono TEXT,
            area TEXT,
            creador TEXT
        )
    ''')

    
    # 7. Tabla de Configuración del Dólar
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )
    ''')
    
    # Inyección segura de valores por defecto (Si ya existen, los ignora)
    try:
        cursor.execute("INSERT OR IGNORE INTO carpetas (nombre, creador) VALUES ('General', 'Sistema')")
        cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('dolar', '17.35')")
        cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('dolar_fecha', '16/09/2026')")
        cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('dolar_hora', '12:00')")
        cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('dolar_usuario', 'Sistema')")
        cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('dolar_anterior', '17.35')")

        conn.commit()
    except Exception as e:
        print(f"Aviso en base de datos: {e}")
        
    # EL CIERRE AL FINAL: Ahora sí cerramos la base de datos de forma segura
    conn.close()


@app.route('/')
def inicio():
    if 'usuario' not in session or 'puesto' not in session:
        return redirect(url_for('logout'))
    
    conn = sqlite3.connect('intranet_nueva.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT m.id, m.autor, m.contenido, m.es_foto, m.puesto_autor, m.fecha,
               (SELECT COUNT(*) FROM likes WHERE mensaje_id = m.id) as total_likes
        FROM mensajes m ORDER BY m.id DESC
    ''')
    mensajes = cursor.fetchall()
    
    cursor.execute("SELECT mensaje_id FROM likes WHERE usuario = ?", (session['usuario'],))
    mis_likes = [fila[0] for fila in cursor.fetchall()]
    
    # Aquí corregimos los espacios para que queden alineados con los de arriba:
    cursor.execute("SELECT nombre, creador FROM carpetas ORDER BY nombre ASC")
    carpetas = cursor.fetchall()
    cursor.execute("SELECT nombre, creador FROM carpetas ORDER BY nombre ASC")
    carpetas = cursor.fetchall()
    
    # ¡ESTA ES LA LÍNEA QUE FALTA! Agrégala aquí abajo:
    cursor.execute("SELECT nombre_archivo, subido_por, fecha, carpeta FROM archivos ORDER BY id DESC")
    archivos = cursor.fetchall()

    
    cursor.execute("SELECT nombre, creador FROM carpetas ORDER BY nombre ASC")
    carpetas = cursor.fetchall()

    
    cursor.execute("SELECT usuario, puesto, cumpleanos FROM usuarios ORDER BY cumpleanos ASC")
    todos_cumpleanos = cursor.fetchall()
    # NUEVO: Detector automático de cumpleañeros del día de hoy
    dia_hoy = datetime.now().day
    mes_hoy = datetime.now().month
    
    # REGRESAMOS LA CONSULTA EXCELENTE DEL DIRECTORIO CON CORREO
    cursor.execute("SELECT id, nombre, telefono, area, creador, correo FROM directorio ORDER BY nombre ASC")
    contactos = cursor.fetchall()
    cumpleanos_limpios = []
    for usuario_c, puesto_c, fecha_str in todos_cumpleanos:
        es_hoy = 0  # Marcador: 0 = normal, 1 = cumple años hoy
        try:
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d')
            meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
            fecha_bonita = f"{fecha_obj.day} de {meses[fecha_obj.month - 1]}"
            
            # Si el día y el mes coinciden con la fecha actual del servidor, activamos la alerta
            if fecha_obj.day == dia_hoy and fecha_obj.month == mes_hoy:
                es_hoy = 1
        except:
            fecha_bonita = fecha_str
            
        # Pasamos el dato extra "es_hoy" a la lista para el HTML
        cumpleanos_limpios.append((usuario_c, puesto_c, fecha_bonita, es_hoy))
       
    # LECTURA CORREGIDA Y DESEMPAQUETADA DE CONFIGURACIÓN
    conn = sqlite3.connect('intranet_nueva.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT valor FROM configuracion WHERE clave = 'dolar'")
    f_dolar = cursor.fetchone()
    tipo_cambio = f_dolar[0] if f_dolar else "17.35"
    
    cursor.execute("SELECT valor FROM configuracion WHERE clave = 'dolar_fecha'")
    f_fecha = cursor.fetchone()
    d_fecha = f_fecha[0] if f_fecha else "16/09/2026"
    
    cursor.execute("SELECT valor FROM configuracion WHERE clave = 'dolar_hora'")
    f_hora = cursor.fetchone()
    d_hora = f_hora[0] if f_hora else "12:00"
    
    cursor.execute("SELECT valor FROM configuracion WHERE clave = 'dolar_usuario'")
    f_user = cursor.fetchone()
    d_usuario = f_user[0] if f_user else "Sistema"
    
    # ¡AQUÍ ESTÁ LA CORRECCIÓN CLAVE! Le agregamos el [0] para desenvolver el precio viejo:
    cursor.execute("SELECT valor FROM configuracion WHERE clave = 'dolar_anterior'")
    f_ant = cursor.fetchone()
    d_anterior = f_ant[0] if f_ant else "17.35"

    cursor.execute("SELECT id, titulo, enlace, creador FROM links_interes ORDER BY titulo ASC")
    links = cursor.fetchall()
    
    conn.close()

    return render_template('intranet.html', mensajes=mensajes, mis_likes=mis_likes, archivos=archivos, 
                           carpetas=carpetas, cumpleanos=cumpleanos_limpios, usuario=session['usuario'], puesto=session['puesto'], contactos=contactos, 				   tipo_cambio=tipo_cambio, d_fecha=d_fecha, d_hora=d_hora, d_usuario=d_usuario, d_anterior=d_anterior, links=links)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        clave = request.form['clave']
        
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        cursor.execute("SELECT puesto FROM usuarios WHERE usuario=? AND clave=?", (usuario, clave))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['usuario'] = usuario
            session['puesto'] = user[0]
            return redirect(url_for('inicio'))
        else:
            return "Usuario o contraseña incorrectos. <a href='/login'>Volver</a>"
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        usuario = request.form['usuario']
        clave = request.form['clave']
        puesto = request.form['puesto']
        cumpleanos = request.form['cumpleanos']
        
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO usuarios (usuario, clave, puesto, cumpleanos) VALUES (?, ?, ?, ?)", 
                           (usuario, clave, puesto, cumpleanos))
            conn.commit()
            conn.close()
            return "Usuario registrado con éxito. <a href='/login'>Ir al Login</a>"
        except sqlite3.IntegrityError:
            conn.close()
            return "El nombre de usuario ya existe. <a href='/registro'>Intentar otro</a>"
    return render_template('registro.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    session.pop('puesto', None)
    return redirect(url_for('login'))

@app.route('/mensaje', methods=['POST'])
def nuevo_mensaje():
    if 'usuario' not in session:
        return redirect(url_for('login'))
        
    contenido = request.form.get('contenido', '')
    foto = request.files.get('foto')
    es_foto = 0
    fecha_actual = datetime.now().strftime('%d/%m/%Y %H:%M')

    if foto and foto.filename != '' and es_imagen(foto.filename):
        filename = secure_filename(foto.filename)
        foto.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        contenido = filename
        es_foto = 1

    if contenido or es_foto:
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO mensajes (autor, contenido, es_foto, puesto_autor, fecha) VALUES (?, ?, ?, ?, ?)", 
                       (session['usuario'], contenido, es_foto, session['puesto'], fecha_actual))
        conn.commit()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/crear_carpeta', methods=['POST'])
def crear_carpeta():
    if 'usuario' in session:
        nombre_carpeta = request.form.get('nombre_carpeta', '').strip()
        if nombre_carpeta:
            conn = sqlite3.connect('intranet_nueva.db')
            cursor = conn.cursor()
            try:
                usuario_activo = session['usuario']
                cursor.execute("INSERT INTO carpetas (nombre, creador) VALUES (?, ?)", (nombre_carpeta, usuario_activo))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            conn.close()
    return redirect(url_for('inicio'))

@app.route('/borrar_carpeta/<string:nombre>')
def borrar_carpeta(nombre):
    if 'usuario' in session:
        if nombre == 'General':
            return redirect(url_for('inicio'))
            
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        cursor.execute("SELECT creador FROM carpetas WHERE nombre=?", (nombre,))
        carpeta_info = cursor.fetchone()
        
        if carpeta_info and (carpeta_info[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            cursor.execute("UPDATE archivos SET carpeta='General' WHERE carpeta=?", (nombre,))
            cursor.execute("DELETE FROM carpetas WHERE nombre=?", (nombre,))
            conn.commit()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/subir', methods=['POST'])
def subir_archivo():
    if 'usuario' in session and 'archivo' in request.files:
        f = request.files['archivo']
        carpeta_destino = request.form.get('carpeta_destino', 'General')
        if f.filename != '':
            filename = secure_filename(f.filename)
            fecha_actual = datetime.now().strftime('%d/%m/%Y %H:%M')
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            conn = sqlite3.connect('intranet_nueva.db')
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO archivos (nombre_archivo, subido_por, fecha, carpeta) VALUES (?, ?, ?, ?)", 
                               (filename, session['usuario'], fecha_actual, carpeta_destino))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            conn.close()
    return redirect(url_for('inicio'))

@app.route('/descargar/<filename>')
def descargar_archivo(filename):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/borrar_archivo/<filename>')
def borrar_archivo(filename):
    if 'usuario' in session:
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        cursor.execute("SELECT subido_por FROM archivos WHERE nombre_archivo=?", (filename,))
        archivo_info = cursor.fetchone()
        if archivo_info and archivo_info[0] == session['usuario']:
            cursor.execute("DELETE FROM archivos WHERE nombre_archivo=?", (filename,))
            conn.commit()
            ruta_archivo = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(ruta_archivo):
                os.remove(ruta_archivo)
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/publicar', methods=['POST'])
def publicar():
    if 'usuario' in session:
        contenido = request.form.get('contenido', '').strip()
        foto = request.files.get('foto')
        nombre_imagen_bd = None
        es_foto = 0
        
        # 1. Procesamos la foto si el usuario adjuntó una
        if foto and foto.filename != '' and es_imagen(foto.filename):
            filename = secure_filename(foto.filename)
            # Creamos la carpeta de uploads automáticamente si no existe en static
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            # Guardamos el archivo físicamente en static/uploads/
            foto.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            nombre_imagen_bd = filename
            es_foto = 1

        # 2. Si el usuario escribió texto, o subió una foto (o ambas), guardamos el anuncio
        if contenido or es_foto:
            fecha_actual = datetime.now().strftime('%d/%m/%Y %H:%M')
            conn = sqlite3.connect('intranet_nueva.db')
            cursor = conn.cursor()
            
            # Si hay foto, guardamos el nombre de la imagen en 'contenido'. Si no, guardamos el texto normal.
            texto_guardar = nombre_imagen_bd if es_foto else contenido
            # Guardamos un dato extra: si hay foto y texto juntos, metemos el texto en la BD (opcional)
            if es_foto and contenido:
                texto_guardar = f"{contenido}|{nombre_imagen_bd}"
                
            cursor.execute("INSERT INTO mensajes (autor, contenido, es_foto, puesto_autor, fecha) VALUES (?, ?, ?, ?, ?)",
                           (session['usuario'], texto_guardar, es_foto, session['puesto'], fecha_actual))
            conn.commit()
            conn.close()
            
    return redirect(url_for('inicio'))


@app.route('/borrar_mensaje/<int:id>')
def borrar_mensaje(id):
    if 'usuario' in session:
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        cursor.execute("SELECT autor FROM mensajes WHERE id=?", (id,))
        msg = cursor.fetchone()
        if msg and (msg[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            cursor.execute("DELETE FROM mensajes WHERE id=?", (id,))
            conn.commit()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/like/<int:id>')
def dar_like(id):
    if 'usuario' in session:
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        try:
            # Registramos el Me Gusta cruzando el ID del mensaje con el usuario activo
            cursor.execute("INSERT INTO likes (mensaje_id, usuario) VALUES (?, ?)", (id, session['usuario']))
            conn.commit()
        except sqlite3.IntegrityError:
            # Si el usuario ya le había dado like, lo retira (Toggle de Like)
            cursor.execute("DELETE FROM likes WHERE mensaje_id=? AND usuario=?", (id, session['usuario']))
            conn.commit()
        conn.close()
    return redirect(url_for('inicio'))


@app.route('/crear_contacto', methods=['POST'])
def crear_contacto():
    if 'usuario' in session:
        nombre = request.form.get('nom_contacto', '').strip()
        telefono = request.form.get('tel_contacto', '').strip()
        area = request.form.get('area_contacto', '').strip()
        correo = request.form.get('correo_contacto', '').strip() or 'No registrado'
        if nombre and telefono:
            conn = sqlite3.connect('intranet_nueva.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO directorio (nombre, telefono, area, creador, correo) VALUES (?, ?, ?, ?, ?)", 
                           (nombre, telefono, area, session['usuario'], correo))
            conn.commit()
            conn.close()
    return redirect(url_for('inicio'))

@app.route('/borrar_contacto/<int:id>')
def borrar_contacto(id):
    if 'usuario' in session:
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        cursor.execute("SELECT creador FROM directorio WHERE id=?", (id,))
        contacto = cursor.fetchone()
        if contacto and (contacto[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            cursor.execute("DELETE FROM directorio WHERE id=?", (id,))
            conn.commit()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/editar_contacto/<int:id>', methods=['POST'])
def editar_contacto(id):
    if 'usuario' in session:
        nuevo_tel = request.form.get('nuevo_telefono', '').strip()
        nuevo_correo = request.form.get('nuevo_correo', '').strip()
        
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        cursor.execute("SELECT creador FROM directorio WHERE id=?", (id,))
        contacto = cursor.fetchone()
        
        if contacto and (contacto[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            if nuevo_tel:
                cursor.execute("UPDATE directorio SET telefono=? WHERE id=?", (nuevo_tel, id))
            if nuevo_correo:
                cursor.execute("UPDATE directorio SET correo=? WHERE id=?", (nuevo_correo, id))
            conn.commit()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/actualizar_dolar', methods=['POST'])
def actualizar_dolar():
    if 'usuario' in session:
        puesto_usuario = session['puesto'].lower()
        if 'administrador' in puesto_usuario or 'administración' in puesto_usuario or 'administracion' in puesto_usuario:
            nuevo_precio = request.form.get('nuevo_dolar', '').strip()
            if nuevo_precio:
                fecha_actual = datetime.now().strftime('%d/%m/%Y')
                hora_actual = datetime.now().strftime('%H:%M')
                usuario_cambio = session['usuario']
                
                conn = sqlite3.connect('intranet_nueva.db')
                cursor = conn.cursor()
                
                # 1. ¡EL TRUCO! Primero leemos el valor actual en la BD antes de borrarlo
                cursor.execute("SELECT valor FROM configuracion WHERE clave = 'dolar'")
                precio_actual_bd = cursor.fetchone()
                precio_viejo = precio_actual_bd[0] if precio_actual_bd else "17.35"
                
                # 2. Guardamos el precio viejo en la casilla 'dolar_anterior'
                cursor.execute("UPDATE configuracion SET valor = ? WHERE clave = 'dolar_anterior'", (precio_viejo,))
                
                # 3. Guardamos los nuevos datos de la bitácora normal
                cursor.execute("UPDATE configuracion SET valor = ? WHERE clave = 'dolar'", (nuevo_precio,))
                cursor.execute("UPDATE configuracion SET valor = ? WHERE clave = 'dolar_fecha'", (fecha_actual,))
                cursor.execute("UPDATE configuracion SET valor = ? WHERE clave = 'dolar_hora'", (hora_actual,))
                cursor.execute("UPDATE configuracion SET valor = ? WHERE clave = 'dolar_usuario'", (usuario_cambio,))
                
                conn.commit()
                conn.close()
    return redirect(url_for('inicio'))

@app.route('/crear_link', methods=['POST'])
def crear_link():
    if 'usuario' in session:
        titulo = request.form.get('tit_link', '').strip()
        enlace = request.form.get('url_link', '').strip()
        
        if enlace and not enlace.startswith(('http://', 'https://')):
            enlace = 'https://' + enlace
            
        if titulo and enlace:
            conn = sqlite3.connect('intranet_nueva.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO links_interes (titulo, enlace, creador) VALUES (?, ?, ?)", 
                           (titulo, enlace, session['usuario']))
            conn.commit()
            conn.close()
    return redirect(url_for('inicio'))

@app.route('/borrar_link/<int:id>')
def borrar_link(id):
    if 'usuario' in session:
        conn = sqlite3.connect('intranet_nueva.db')
        cursor = conn.cursor()
        cursor.execute("SELECT creador FROM links_interes WHERE id=?", (id,))
        link_info = cursor.fetchone()
        
        if link_info and (link_info[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            cursor.execute("DELETE FROM links_interes WHERE id=?", (id,))
            conn.commit()
        conn.close()
    return redirect(url_for('inicio'))

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)