import urllib.request
import json
import os
import time
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.utils import secure_filename
import psycopg2
from datetime import datetime
from supabase import create_client  # <--- NUEVO

app = Flask(__name__)
app.secret_key = 'clave_secreta_para_sesiones'

# --- CONFIGURACIÓN DE SUPABASE STORAGE ---
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://hyswibgorwuzwvipjlth.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'sb_secret_bzS5XdLi9G9Dd4MV-aqodg_tJBs9Sv_')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
BUCKET_NAME = 'intranet'

EXTENSIONES_IMAGEN = {'png', 'jpg', 'jpeg', 'gif'}

def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("La variable DATABASE_URL no está configurada.")
    conn = psycopg2.connect(database_url)
    return conn

def es_imagen(filename):
    if '.' in filename:
        ext = filename.rsplit('.', 1)[1].lower()
        return ext in EXTENSIONES_IMAGEN
    return False

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            usuario TEXT UNIQUE,
            clave TEXT,
            puesto TEXT,
            cumpleanos TEXT,
            email VARCHAR(255) UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mensajes (
            id SERIAL PRIMARY KEY,
            autor TEXT,
            contenido TEXT,
            es_foto INTEGER DEFAULT 0,
            puesto_autor TEXT,
            fecha TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            id SERIAL PRIMARY KEY,
            mensaje_id INTEGER,
            usuario TEXT,
            UNIQUE(mensaje_id, usuario)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS carpetas (
            id SERIAL PRIMARY KEY,
            nombre TEXT,
            creador TEXT DEFAULT 'Sistema',
            padre_id INTEGER REFERENCES carpetas(id) ON DELETE CASCADE NULL
        )
    ''')
    
    try:
        cursor.execute("ALTER TABLE carpetas ADD COLUMN IF NOT EXISTS padre_id INTEGER REFERENCES carpetas(id) ON DELETE CASCADE NULL;")
        conn.commit()
    except Exception:
        conn.rollback()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS archivos (
            id SERIAL PRIMARY KEY,
            nombre_archivo TEXT,
            subido_por TEXT,
            fecha TEXT,
            carpeta TEXT DEFAULT 'General',
            carpeta_id INTEGER REFERENCES carpetas(id) ON DELETE CASCADE NULL
        )
    ''')

    try:
        cursor.execute("ALTER TABLE archivos ADD COLUMN IF NOT EXISTS carpeta_id INTEGER REFERENCES carpetas(id) ON DELETE CASCADE NULL;")
        conn.commit()
    except Exception:
        conn.rollback()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS directorio (
            id SERIAL PRIMARY KEY,
            nombre TEXT,
            telefono TEXT,
            area TEXT,
            creador TEXT,
            correo TEXT DEFAULT 'No registrado'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS links_interes (
            id SERIAL PRIMARY KEY,
            titulo TEXT,
            enlace TEXT,
            creador TEXT
        )
    ''')
    
    try:
        cursor.execute("INSERT INTO configuracion (clave, valor) VALUES ('dolar', '17.35') ON CONFLICT (clave) DO NOTHING")
        cursor.execute("INSERT INTO configuracion (clave, valor) VALUES ('dolar_fecha', '16/09/2026') ON CONFLICT (clave) DO NOTHING")
        cursor.execute("INSERT INTO configuracion (clave, valor) VALUES ('dolar_hora', '12:00') ON CONFLICT (clave) DO NOTHING")
        cursor.execute("INSERT INTO configuracion (clave, valor) VALUES ('dolar_usuario', 'Sistema') ON CONFLICT (clave) DO NOTHING")
        cursor.execute("INSERT INTO configuracion (clave, valor) VALUES ('dolar_anterior', '17.35') ON CONFLICT (clave) DO NOTHING")
        conn.commit()
    except Exception:
        conn.rollback()
        
    cursor.close()
    conn.close()

init_db()

@app.route('/')
def index():
    # Si el usuario ya está autenticado, va directo al inicio
    if 'usuario' in session and 'puesto' in session:
        return redirect(url_for('inicio'))
    
    # Si no hay sesión activa, va al formulario de login
    return redirect(url_for('login'))
    

def obtener_ruta_carpetas(carpeta_actual_id):
    ruta = []
    curr_id = carpeta_actual_id
    conn = get_db_connection()
    cursor = conn.cursor()
    while curr_id is not None:
        cursor.execute("SELECT id, nombre, padre_id FROM carpetas WHERE id=%s", (curr_id,))
        res = cursor.fetchone()
        if res:
            ruta.insert(0, {'id': res[0], 'nombre': res[1]})
            curr_id = res[2]
        else:
            break
    cursor.close()
    conn.close()
    return ruta
    

@app.route('/inicio')
def inicio():
    if 'usuario' not in session or 'puesto' not in session:
        # Si expira la sesión durante una petición AJAX
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'redirect': url_for('login')}), 401
        return redirect(url_for('login'))
    
    # Obtener el folder_id (maneja None si no se especifica)
    carpeta_actual_id = request.args.get('folder_id', type=int)
    if carpeta_actual_id == 0:
        carpeta_actual_id = None

    conn = get_db_connection()
    cursor = conn.cursor()

    # --- CONSULTAS ESPECÍFICAS PARA EL GESTOR DE DOCUMENTOS ---
    # 1. Subcarpetas de la carpeta actual
    if carpeta_actual_id is None:
        cursor.execute("SELECT id, nombre, creador FROM carpetas WHERE padre_id IS NULL ORDER BY nombre ASC")
    else:
        cursor.execute("SELECT id, nombre, creador FROM carpetas WHERE padre_id = %s ORDER BY nombre ASC", (carpeta_actual_id,))
    carpetas = cursor.fetchall()
    
    # 2. Archivos de la carpeta actual
    if carpeta_actual_id is None:
        cursor.execute("SELECT id, nombre_archivo, subido_por, fecha, carpeta_id FROM archivos WHERE carpeta_id IS NULL ORDER BY id DESC")
    else:
        cursor.execute("SELECT id, nombre_archivo, subido_por, fecha, carpeta_id FROM archivos WHERE carpeta_id = %s ORDER BY id DESC", (carpeta_actual_id,))
    archivos = cursor.fetchall()

    # 3. Ruta de migas de pan (Breadcrumbs)
    breadcrumbs = obtener_ruta_carpetas(carpeta_actual_id)

    # ------------------------------------------------------------------
    # PASO 2: DETECCIÓN DE PETICIÓN AJAX (Navegación de carpetas)
    # Devolvemos directamente 'intranet.html' para evitar errores de plantillas faltantes.
    # ------------------------------------------------------------------
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        cursor.close()
        conn.close()
        
        return render_template(
            'intranet.html',
            archivos=archivos,
            carpetas=carpetas,
            carpeta_actual_id=carpeta_actual_id,
            breadcrumbs=breadcrumbs,
            usuario=session.get('usuario'),
            puesto=session.get('puesto')
        )

    # ------------------------------------------------------------------
    # CARGA COMPLETA (Solo si el usuario recarga manualmente la página F5)
    # ------------------------------------------------------------------
    # Mensajes y Likes
    cursor.execute('''
        SELECT m.id, m.autor, m.contenido, m.es_foto, m.puesto_autor, m.fecha,
               (SELECT COUNT(*) FROM likes WHERE mensaje_id = m.id) as total_likes
        FROM mensajes m ORDER BY m.id DESC
    ''')
    mensajes = cursor.fetchall()
    
    cursor.execute("SELECT mensaje_id FROM likes WHERE usuario = %s", (session['usuario'],))
    mis_likes = [fila[0] for fila in cursor.fetchall()]

    # Cumpleaños
    cursor.execute("SELECT usuario, puesto, cumpleanos FROM usuarios ORDER BY cumpleanos ASC")
    todos_cumpleanos = cursor.fetchall()
    
    dia_hoy = datetime.now().day
    mes_hoy = datetime.now().month
    
    cumpleanos_limpios = []
    for usuario_c, puesto_c, fecha_str in todos_cumpleanos:
        es_hoy = 0
        try:
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d')
            meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
            fecha_bonita = f"{fecha_obj.day} de {meses[fecha_obj.month - 1]}"
            if fecha_obj.day == dia_hoy and fecha_obj.month == mes_hoy:
                es_hoy = 1
        except Exception:
            fecha_bonita = fecha_str
        cumpleanos_limpios.append((usuario_c, puesto_c, fecha_bonita, es_hoy))

    # Directorio y Configuración
    cursor.execute("SELECT id, nombre, telefono, area, creador, correo FROM directorio ORDER BY nombre ASC")
    contactos = cursor.fetchall()
    
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
    
    cursor.execute("SELECT valor FROM configuracion WHERE clave = 'dolar_anterior'")
    f_ant = cursor.fetchone()
    d_anterior = f_ant[0] if f_ant else "17.35"

    cursor.execute("SELECT id, titulo, enlace, creador FROM links_interes ORDER BY titulo ASC")
    links = cursor.fetchall()
    
    cursor.close()
    conn.close()

    return render_template(
        'intranet.html',
        mensajes=mensajes,
        mis_likes=mis_likes,
        archivos=archivos,
        carpetas=carpetas,
        carpeta_actual_id=carpeta_actual_id,
        breadcrumbs=breadcrumbs,
        cumpleanos=cumpleanos_limpios,
        contactos=contactos,
        tipo_cambio=tipo_cambio,
        d_fecha=d_fecha,
        d_hora=d_hora,
        d_usuario=d_usuario,
        d_anterior=d_anterior,
        links=links,
        usuario=session.get('usuario'),
        puesto=session.get('puesto')
    )
    
@app.route('/crear_carpeta', methods=['POST'])
def crear_carpeta():
    if 'usuario' not in session:
        return jsonify({'success': False, 'message': 'Sesión no activa'}), 401

    nombre_carpeta = request.form.get('nombre_carpeta', '').strip()
    raw_padre_id = request.form.get('padre_id')
    padre_id = int(raw_padre_id) if raw_padre_id and raw_padre_id.isdigit() else None

    if not nombre_carpeta:
        return jsonify({'success': False, 'message': 'El nombre de la carpeta no puede estar vacío.'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM carpetas 
            WHERE LOWER(nombre) = LOWER(%s) AND padre_id IS NOT DISTINCT FROM %s
        """, (nombre_carpeta, padre_id))
        
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({
                'success': False, 
                'message': f"La carpeta '{nombre_carpeta}' ya existe en esta ubicación."
            }), 400

        cursor.execute("""
            INSERT INTO carpetas (nombre, creador, padre_id) 
            VALUES (%s, %s, %s)
        """, (nombre_carpeta, session['usuario'], padre_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'message': 'Carpeta creada correctamente.'})

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        print("Error al crear carpeta:", e)
        return jsonify({'success': False, 'message': f'Error en el servidor: {str(e)}'}), 500

@app.route('/borrar_carpeta/<int:id>')
def borrar_carpeta(id):
    if 'usuario' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT creador, padre_id FROM carpetas WHERE id=%s", (id,))
        carpeta_info = cursor.fetchone()
        
        padre_id = None
        if carpeta_info:
            padre_id = carpeta_info[1]
            if carpeta_info[0] == session['usuario'] or session['puesto'] == 'Administrador':
                cursor.execute("DELETE FROM carpetas WHERE id=%s", (id,))
                conn.commit()
        cursor.close()
        conn.close()
        
        if padre_id:
            return redirect(url_for('inicio', folder_id=padre_id))
    return redirect(url_for('inicio'))

@app.route('/subir', methods=['POST'])
def subir_archivo():
    if 'usuario' not in session:
        return jsonify({'success': False, 'message': 'Sesión no activa'}), 401

    if 'archivo' not in request.files:
        return jsonify({'success': False, 'message': 'No se envió ningún archivo.'}), 400

    f = request.files['archivo']
    raw_carpeta_id = request.form.get('carpeta_id')
    carpeta_id = int(raw_carpeta_id) if raw_carpeta_id and raw_carpeta_id.isdigit() else None

    if f.filename == '':
        return jsonify({'success': False, 'message': 'Nombre de archivo vacío.'}), 400

    nombre_original = secure_filename(f.filename)
    conn = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Validar duplicados
        cursor.execute("SELECT carpeta FROM archivos WHERE LOWER(nombre_archivo) = LOWER(%s)", (nombre_original,))
        archivo_existente = cursor.fetchone()

        if archivo_existente:
            carpeta_donde_esta = archivo_existente['carpeta'] if isinstance(archivo_existente, dict) else archivo_existente[0]
            cursor.close()
            conn.close()
            return jsonify({
                'success': False, 
                'message': f"El archivo '{nombre_original}' ya existe en la carpeta '{carpeta_donde_esta}'."
            }), 400

        # Subir a Supabase Storage
        bytes_archivo = f.read()
        path_supabase = f"archivos/{nombre_original}"

        supabase.storage.from_(BUCKET_NAME).upload(
            path=path_supabase,
            file=bytes_archivo,
            file_options={"content-type": f.content_type or "application/octet-stream"}
        )

        fecha_actual = datetime.now().strftime('%d/%m/%Y %H:%M')
        nombre_carpeta = 'General'

        if carpeta_id:
            cursor.execute("SELECT nombre FROM carpetas WHERE id = %s", (carpeta_id,))
            res = cursor.fetchone()
            if res:
                nombre_carpeta = res['nombre'] if isinstance(res, dict) else res[0]

        cursor.execute("""
            INSERT INTO archivos (nombre_archivo, subido_por, fecha, carpeta, carpeta_id) 
            VALUES (%s, %s, %s, %s, %s)
        """, (nombre_original, session['usuario'], fecha_actual, nombre_carpeta, carpeta_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'message': 'Archivo subido correctamente.'})

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        print(f"Error en /subir: {e}")
        return jsonify({'success': False, 'message': f"Error al subir archivo: {str(e)}"}), 500

    if carpeta_id:
        return redirect(url_for('inicio', folder_id=carpeta_id))
    return redirect(url_for('inicio'))
    
# --- MODIFICACIÓN EN BORRAR ARCHIVO (DRIVE) ---
@app.route('/borrar_archivo/<int:id>')
def borrar_archivo(id):
    if 'usuario' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT subido_por, nombre_archivo, carpeta_id FROM archivos WHERE id=%s", (id,))
        archivo_info = cursor.fetchone()
        
        carpeta_id = None
        if archivo_info:
            subido_por = (archivo_info[0] or '').lower().strip()
            nombre_archivo = archivo_info[1]
            carpeta_id = archivo_info[2]
            
            usuario_actual = (session.get('usuario') or '').lower().strip()
            puesto_actual = (session.get('puesto') or '').lower().strip()
            
            if subido_por == usuario_actual or 'admin' in puesto_actual:
                cursor.execute("DELETE FROM archivos WHERE id=%s", (id,))
                conn.commit()
                
                # Eliminar de Supabase Storage
                try:
                    supabase.storage.from_(BUCKET_NAME).remove([f"archivos/{nombre_archivo}"])
                except Exception as e:
                    print("Error al borrar en Supabase:", e)
                    
        cursor.close()
        conn.close()
        
        if carpeta_id:
            return redirect(url_for('inicio', folder_id=carpeta_id))
    return redirect(url_for('inicio'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        clave = request.form.get('clave')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT puesto FROM usuarios WHERE usuario=%s AND clave=%s", (usuario, clave))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            session['usuario'] = usuario
            session['puesto'] = user[0]
            return redirect(url_for('inicio'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        email = request.form.get('email', '').strip().lower()
        clave = request.form.get('clave')
        puesto = request.form.get('puesto')
        cumpleanos = request.form.get('cumpleanos')

        # 1. Validación de dominio corporativo
        if not email.endswith('@austral.mx'):
            flash('Acceso restringido: Solo se permiten correos con el dominio @austral.mx')
            return redirect(url_for('registro'))

        # 2. Inserción usando get_db_connection()
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO usuarios (usuario, email, clave, puesto, cumpleanos)
                VALUES (%s, %s, %s, %s, %s)
            """, (usuario, email, clave, puesto, cumpleanos))
            
            conn.commit()
            cursor.close()
            conn.close()

            flash('Cuenta creada exitosamente. Ya puedes iniciar sesión.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            if conn:
                conn.rollback()
                conn.close()
            print(f"Error en registro: {e}")
            flash('Error al registrar: El usuario o el correo ya se encuentran registrados.')
            return redirect(url_for('registro'))

    return render_template('registro.html')
    
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- MODIFICACIÓN EN DESCARGAR Y ABRIR ARCHIVO ---
@app.route('/descargar/<path:filename>')
def descargar_archivo(filename):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    # Redirigir a la URL pública de Supabase con forzado de descarga
    url_publica = supabase.storage.from_(BUCKET_NAME).get_public_url(f"archivos/{filename}")
    return redirect(url_publica)
    
@app.route('/abrir_archivo/<path:filename>')
def abrir_archivo(filename):
    if 'usuario' not in session:
        return jsonify({'success': False, 'message': 'Sesión no activa'}), 401

    try:
        # Obtener URL pública de Supabase Storage
        url_publica = supabase.storage.from_(BUCKET_NAME).get_public_url(f"archivos/{filename}")
        return redirect(url_publica)
    except Exception as e:
        return f"Error al abrir el archivo: {e}", 500

# --- MODIFICACIÓN EN PUBLICAR (MURO DE ANUNCIOS) ---
@app.route('/publicar', methods=['POST'])
def publicar():
    if 'usuario' in session:
        contenido = request.form.get('contenido', '').strip()
        foto = request.files.get('foto')
        url_imagen_publica = None
        es_foto = 0
        
        if foto and foto.filename != '' and es_imagen(foto.filename):
            nombre_limpio = secure_filename(foto.filename)
            filename = f"muro_{int(time.time())}_{nombre_limpio}"
            bytes_foto = foto.read()

            # Subir foto a la carpeta publicaciones dentro del bucket
            supabase.storage.from_(BUCKET_NAME).upload(
                path=f"publicaciones/{filename}",
                file=bytes_foto,
                file_options={"content-type": foto.content_type}
            )

            # Obtener URL pública completa de Supabase
            url_imagen_publica = supabase.storage.from_(BUCKET_NAME).get_public_url(f"publicaciones/{filename}")
            es_foto = 1

        if contenido or es_foto:
            fecha_actual = datetime.now().strftime('%d/%m/%Y %H:%M')
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Guardamos la URL pública en lugar de solo el nombre
            texto_guardar = url_imagen_publica if es_foto else contenido
            if es_foto and contenido:
                texto_guardar = f"{contenido}|{url_imagen_publica}"

            cursor.execute("INSERT INTO mensajes (autor, contenido, es_foto, puesto_autor, fecha) VALUES (%s, %s, %s, %s, %s)",
                           (session['usuario'], texto_guardar, es_foto, session['puesto'], fecha_actual))
            conn.commit()
            cursor.close()
            conn.close()
    return redirect(url_for('inicio'))

@app.route('/borrar_mensaje/<int:id>')
def borrar_mensaje(id):
    if 'usuario' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT autor FROM mensajes WHERE id=%s", (id,))
        msg = cursor.fetchone()
        if msg and (msg[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            cursor.execute("DELETE FROM mensajes WHERE id=%s", (id,))
            conn.commit()
        cursor.close()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/like/<int:id>')
def dar_like(id):
    if 'usuario' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO likes (mensaje_id, usuario) VALUES (%s, %s)", (id, session['usuario']))
            conn.commit()
        except psycopg2.IntegrityError:
            conn.rollback()
            cursor.execute("DELETE FROM likes WHERE mensaje_id=%s AND usuario=%s", (id, session['usuario']))
            conn.commit()
        cursor.close()
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
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO directorio (nombre, telefono, area, creador, correo) VALUES (%s, %s, %s, %s, %s)", 
                           (nombre, telefono, area, session['usuario'], correo))
            conn.commit()
            cursor.close()
            conn.close()
    return redirect(url_for('inicio'))

@app.route('/borrar_contacto/<int:id>')
def borrar_contacto(id):
    if 'usuario' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT creador FROM directorio WHERE id=%s", (id,))
        contacto = cursor.fetchone()
        if contacto and (contacto[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            cursor.execute("DELETE FROM directorio WHERE id=%s", (id,))
            conn.commit()
        cursor.close()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/editar_contacto/<int:id>', methods=['POST'])
def editar_contacto(id):
    if 'usuario' in session:
        nuevo_tel = request.form.get('nuevo_telefono', '').strip()
        nuevo_correo = request.form.get('nuevo_correo', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT creador FROM directorio WHERE id=%s", (id,))
        contacto = cursor.fetchone()
        if contacto and (contacto[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            if nuevo_tel:
                cursor.execute("UPDATE directorio SET telefono=%s WHERE id=%s", (nuevo_tel, id))
            if nuevo_correo:
                cursor.execute("UPDATE directorio SET correo=%s WHERE id=%s", (nuevo_correo, id))
            conn.commit()
        cursor.close()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/actualizar_tipo_cambio', methods=['POST'])
def actualizar_tipo_cambio():
    if 'usuario' in session:
        puesto_usuario = session.get('puesto', '').lower()
        if 'administrador' in puesto_usuario or 'administración' in puesto_usuario or 'administracion' in puesto_usuario:
            nuevo_precio = request.form.get('nuevo_tc', '').strip()
            if nuevo_precio:
                fecha_actual = datetime.now().strftime('%d/%m/%Y')
                hora_actual = datetime.now().strftime('%H:%M')
                usuario_cambio = session['usuario']
                
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT valor FROM configuracion WHERE clave = 'dolar'")
                precio_actual_bd = cursor.fetchone()
                precio_viejo = precio_actual_bd[0] if precio_actual_bd else "17.35"
                
                # Actualización de la configuración existente
                cursor.execute("UPDATE configuracion SET valor = %s WHERE clave = 'dolar_anterior'", (precio_viejo,))
                cursor.execute("UPDATE configuracion SET valor = %s WHERE clave = 'dolar'", (nuevo_precio,))
                cursor.execute("UPDATE configuracion SET valor = %s WHERE clave = 'dolar_fecha'", (fecha_actual,))
                cursor.execute("UPDATE configuracion SET valor = %s WHERE clave = 'dolar_hora'", (hora_actual,))
                cursor.execute("UPDATE configuracion SET valor = %s WHERE clave = 'dolar_usuario'", (usuario_cambio,))
                
                # --- PASO 2: INSERTAR EN EL HISTORIAL DE TIPO DE CAMBIO ---
                cursor.execute("""
                    INSERT INTO historial_tc (valor, modificado_por, fecha)
                    VALUES (%s, %s, NOW())
                """, (nuevo_precio, usuario_cambio))
                # ---------------------------------------------------------

                conn.commit()
                cursor.close()
                conn.close()
                
                return jsonify({"success": True, "nuevo_valor": nuevo_precio})
    return jsonify({"success": False, "error": "No autorizado o valor inválido"}), 400

@app.route('/crear_link', methods=['POST'])
def crear_link():
    if 'usuario' in session:
        titulo = request.form.get('tit_link', '').strip()
        enlace = request.form.get('url_link', '').strip()
        if enlace and not enlace.startswith(('http://', 'https://')):
            enlace = 'https://' + enlace
        if titulo and enlace:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO links_interes (titulo, enlace, creador) VALUES (%s, %s, %s)", 
                           (titulo, enlace, session['usuario']))
            conn.commit()
            cursor.close()
            conn.close()
    return redirect(url_for('inicio'))

@app.route('/borrar_link/<int:id>')
def borrar_link(id):
    if 'usuario' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT creador FROM links_interes WHERE id=%s", (id,))
        link_info = cursor.fetchone()
        if link_info and (link_info[0] == session['usuario'] or session['puesto'] == 'Administrador'):
            cursor.execute("DELETE FROM links_interes WHERE id=%s", (id,))
            conn.commit()
        cursor.close()
        conn.close()
    return redirect(url_for('inicio'))

@app.route('/obtener_historial_tc', methods=['GET'])
def obtener_historial_tc():
    if 'usuario' not in session:
        return jsonify({'success': False, 'message': 'Sesión no activa'}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT valor, modificado_por, TO_CHAR(fecha, 'DD/MM/YYYY HH24:MI') as fecha_formateada
            FROM historial_tc 
            ORDER BY id DESC 
            LIMIT 20
        """)
        logs = cursor.fetchall()
        
        resultado = []
        for log in logs:
            if isinstance(log, dict):
                resultado.append(log)
            else:
                resultado.append({
                    'valor': str(log[0]),
                    'modificado_por': log[1],
                    'fecha_formateada': log[2]
                })
                
        return jsonify({'success': True, 'historial': resultado})
    except Exception as e:
        print(f"Error al consultar historial_tc: {e}")
        return jsonify({'success': False, 'historial': []})
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
