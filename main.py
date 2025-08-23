from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import httpx
import asyncio
import os
from typing import Dict, List, Any, Optional
import json
from pydantic import BaseModel
from datetime import datetime
import logging
from collections import defaultdict
import re
from urllib.parse import unquote
from dotenv import load_dotenv

load_dotenv()

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="CEPREUNA API",
    description="API para visualización de estudiantes inscritos",
    version="1.0.0"
)

# 🔥 CORS mejorado para Render
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://localhost:5173", 
        "http://localhost:8080",
        "http://localhost:8001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8001",
        "https://*.onrender.com",
        # Agrega aquí tu dominio personalizado si tienes
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Variables globales para cache y autenticación
auth_cookies: Optional[str] = None
csrf_token: Optional[str] = None
cached_data: Optional[Dict] = None
cache_timestamp: Optional[datetime] = None
session_timestamp: Optional[datetime] = None
# 🔥 NUEVO: Cache específico para vacantes
cached_vacantes_data: Optional[Dict] = None
vacantes_cache_timestamp: Optional[datetime] = None
CACHE_DURATION = 300  # 5 minutos
SESSION_DURATION = 1800  # 30 minutos
MAX_RETRY_ATTEMPTS = 3

# Modelos Pydantic
class EstudianteStats(BaseModel):
    total: int
    por_area: Dict[str, int]
    por_sede: Dict[str, int]
    por_turno: Dict[str, int]
    por_sede_turno: Dict[str, int]
    detalle_completo: Dict[str, Dict[str, Dict[str, int]]]
    ultimo_update: str

# 🔥 NUEVO: Modelo para estadísticas de vacantes
class VacantesStats(BaseModel):
    total: int
    por_area: Dict[str, int]
    por_sede: Dict[str, int]
    por_turno: Dict[str, int]
    por_sede_turno: Dict[str, int]
    detalle_completo: Dict[str, Dict[str, Dict[str, int]]]
    ultimo_update: str

class LoginData(BaseModel):
    email: str
    password: str

class DNIRequest(BaseModel):
    dni: str

class FichaResponse(BaseModel):
    download_url: str
    estudiante: Dict[str, Any]
    token: str

# 🔥 Configuración desde variables de entorno con fallbacks
CEPREUNA_EMAIL = os.getenv("CEPREUNA_EMAIL")
CEPREUNA_PASSWORD = os.getenv("CEPREUNA_PASSWORD")
BASE_URL = "https://sistemas.cepreuna.edu.pe"
LOGIN_URL = f"{BASE_URL}/login"
DATA_URL = f"{BASE_URL}/intranet/inscripcion/estudiante/lista/data"
# 🔥 NUEVO: URL para obtener vacantes
VACANTES_URL = f"{BASE_URL}/intranet/administracion/vacantes/lista/data"
ENCRYPT_URL = f"{BASE_URL}/intranet/encrypt/"
DOWNLOAD_URL = f"{BASE_URL}/inscripciones/estudiantes"

# 🔥 Validar variables de entorno críticas al inicio
if not CEPREUNA_EMAIL or not CEPREUNA_PASSWORD:
    logger.error("❌ VARIABLES DE ENTORNO FALTANTES: CEPREUNA_EMAIL y CEPREUNA_PASSWORD son requeridas")
    logger.info("📝 Configura estas variables en Render Dashboard > Environment")

def extract_csrf_token(html_content: str) -> Optional[str]:
    """Extraer token CSRF del HTML de la página de login"""
    csrf_patterns = [
        r'<meta name="csrf-token" content="([^"]+)"',
        r'name="_token" value="([^"]+)"',
        r'"_token":"([^"]+)"'
    ]
    
    for pattern in csrf_patterns:
        match = re.search(pattern, html_content)
        if match:
            return match.group(1)
    
    return None

def is_session_expired() -> bool:
    """Verificar si la sesión ha expirado"""
    global session_timestamp
    if not session_timestamp:
        return True
    
    time_diff = (datetime.now() - session_timestamp).total_seconds()
    return time_diff > SESSION_DURATION

def is_vacantes_cache_valid() -> bool:
    """Verificar si el cache de vacantes sigue siendo válido"""
    if not cached_vacantes_data or not vacantes_cache_timestamp:
        return False
    
    time_diff = (datetime.now() - vacantes_cache_timestamp).total_seconds()
    return time_diff < CACHE_DURATION

async def login_to_cepreuna() -> bool:
    """Realizar login y obtener cookies de autenticación"""
    global auth_cookies, csrf_token, session_timestamp
    
    try:
        logger.info("Iniciando proceso de login...")
        
        # Limpiar credenciales anteriores
        auth_cookies = None
        csrf_token = None
        session_timestamp = None
        
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
        ) as client:
            
            # Primer paso: Obtener la página de login
            logger.info("Obteniendo página de login...")
            login_page = await client.get(LOGIN_URL)
            login_page.raise_for_status()
            
            # Extraer token CSRF del HTML
            csrf_token = extract_csrf_token(login_page.text)
            if not csrf_token:
                logger.warning("No se encontró token CSRF en el HTML")
            else:
                logger.info("Token CSRF obtenido exitosamente")
            
            # Obtener cookies iniciales
            initial_cookies = {}
            for cookie_name, cookie_value in login_page.cookies.items():
                initial_cookies[cookie_name] = cookie_value
            
            # Preparar datos de login
            login_data = {
                "email": CEPREUNA_EMAIL,
                "password": CEPREUNA_PASSWORD
            }
            
            if csrf_token:
                login_data["_token"] = csrf_token
            
            # Headers para el login
            login_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
                "Referer": LOGIN_URL,
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
            
            if csrf_token:
                login_headers["X-CSRF-TOKEN"] = csrf_token
            
            # Realizar login
            logger.info("Enviando credenciales de login...")
            login_response = await client.post(
                LOGIN_URL,
                data=login_data,
                headers=login_headers,
                cookies=initial_cookies
            )
            
            logger.info(f"Respuesta del login - Status: {login_response.status_code}")
            
            # Verificar login exitoso
            if login_response.status_code in [200, 302, 301]:
                # Combinar cookies
                all_cookies = {}
                all_cookies.update(initial_cookies)
                
                for cookie_name, cookie_value in login_response.cookies.items():
                    all_cookies[cookie_name] = cookie_value
                
                required_cookies = ["laravel_session"]
                has_required_cookies = any(cookie in all_cookies for cookie in required_cookies)
                
                if all_cookies and (has_required_cookies or len(all_cookies) > 0):
                    auth_cookies = "; ".join([f"{k}={v}" for k, v in all_cookies.items()])
                    session_timestamp = datetime.now()
                    
                    logger.info(f"Login exitoso, cookies obtenidas: {list(all_cookies.keys())}")
                    return True
                else:
                    logger.error("Login falló: No se obtuvieron cookies válidas")
                    return False
            else:
                logger.error(f"Login falló: Status code {login_response.status_code}")
                return False
                
    except Exception as e:
        logger.error(f"Error durante el login: {str(e)}")
        return False

async def fetch_student_data_with_retry() -> List[Dict]:
    """Obtener datos de estudiantes con reintentos automáticos"""
    
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            logger.info(f"Intento {attempt + 1} de obtener datos de estudiantes")
            return await fetch_student_data()
        except HTTPException as e:
            if e.status_code in [401, 419, 403]:
                logger.warning(f"Error de autenticación en intento {attempt + 1}: {e.detail}")
                if attempt < MAX_RETRY_ATTEMPTS - 1:
                    logger.info("Reintentando con nueva autenticación...")
                    global auth_cookies, csrf_token, session_timestamp
                    auth_cookies = None
                    csrf_token = None
                    session_timestamp = None
                    await asyncio.sleep(2)
                    continue
                else:
                    logger.error("Agotados los intentos de reautenticación")
                    raise HTTPException(status_code=401, detail="No se pudo autenticar después de varios intentos")
            else:
                raise e
        except Exception as e:
            logger.error(f"Error inesperado en intento {attempt + 1}: {str(e)}")
            if attempt < MAX_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(2)
                continue
            else:
                raise HTTPException(status_code=500, detail="Error después de varios intentos")
    
    raise HTTPException(status_code=500, detail="No se pudieron obtener los datos")

# 🔥 NUEVA FUNCIÓN: Obtener datos de vacantes con reintentos
async def fetch_vacantes_data_with_retry() -> List[Dict]:
    """Obtener datos de vacantes con reintentos automáticos"""
    
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            logger.info(f"Intento {attempt + 1} de obtener datos de vacantes")
            return await fetch_vacantes_data()
        except HTTPException as e:
            if e.status_code in [401, 419, 403]:
                logger.warning(f"Error de autenticación en intento {attempt + 1}: {e.detail}")
                if attempt < MAX_RETRY_ATTEMPTS - 1:
                    logger.info("Reintentando con nueva autenticación...")
                    global auth_cookies, csrf_token, session_timestamp
                    auth_cookies = None
                    csrf_token = None
                    session_timestamp = None
                    await asyncio.sleep(2)
                    continue
                else:
                    logger.error("Agotados los intentos de reautenticación")
                    raise HTTPException(status_code=401, detail="No se pudo autenticar después de varios intentos")
            else:
                raise e
        except Exception as e:
            logger.error(f"Error inesperado en intento {attempt + 1}: {str(e)}")
            if attempt < MAX_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(2)
                continue
            else:
                raise HTTPException(status_code=500, detail="Error después de varios intentos")
    
    raise HTTPException(status_code=500, detail="No se pudieron obtener los datos de vacantes")

async def fetch_student_data() -> List[Dict]:
    """Obtener datos de estudiantes desde la API"""
    global auth_cookies, csrf_token, session_timestamp
    
    if not auth_cookies or is_session_expired():
        logger.info("Sesión expirada o no autenticado, iniciando login...")
        login_success = await login_to_cepreuna()
        if not login_success:
            raise HTTPException(status_code=401, detail="No se pudo autenticar con el sistema")
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": f"{BASE_URL}/intranet/inscripcion/estudiante/lista",
            "Connection": "keep-alive",
            "Cookie": auth_cookies
        }
        
        if csrf_token:
            headers["X-CSRF-TOKEN"] = csrf_token
            headers["X-Requested-With"] = "XMLHttpRequest"
        
        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            params = {
                "query": "{}",
                "limit": "10000",
                "ascending": "1",
                "page": "1",
                "byColumn": "1"
            }
            
            logger.info("Obteniendo datos de estudiantes...")
            response = await client.get(DATA_URL, params=params)
            
            logger.info(f"Respuesta API datos - Status: {response.status_code}")
            
            if response.status_code in [401, 419, 403]:
                logger.warning(f"Error de autenticación detectado: {response.status_code}")
                session_timestamp = None
                raise HTTPException(status_code=response.status_code, detail="Sesión expirada")
            
            if response.status_code >= 400:
                logger.error(f"Error HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"Error decodificando JSON: {str(e)}")
                raise HTTPException(status_code=502, detail="Respuesta inválida del servidor")
            
            if isinstance(data, dict) and "data" in data:
                students = data["data"]
            elif isinstance(data, dict) and "students" in data:
                students = data["students"]
            elif isinstance(data, list):
                students = data
            else:
                logger.warning(f"Estructura de datos inesperada: {type(data)}")
                students = []
            
            logger.info(f"Obtenidos {len(students)} registros de estudiantes")
            return students
            
    except httpx.TimeoutException:
        logger.error("Timeout al obtener datos de estudiantes")
        raise HTTPException(status_code=408, detail="Timeout al obtener datos del servidor")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

# 🔥 NUEVA FUNCIÓN: Obtener datos de vacantes
async def fetch_vacantes_data() -> List[Dict]:
    """Obtener datos de vacantes desde la API"""
    global auth_cookies, csrf_token, session_timestamp
    
    if not auth_cookies or is_session_expired():
        logger.info("Sesión expirada o no autenticado, iniciando login...")
        login_success = await login_to_cepreuna()
        if not login_success:
            raise HTTPException(status_code=401, detail="No se pudo autenticar con el sistema")
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": f"{BASE_URL}/intranet/administracion/vacantes/lista",
            "Connection": "keep-alive",
            "Cookie": auth_cookies
        }
        
        if csrf_token:
            headers["X-CSRF-TOKEN"] = csrf_token
            headers["X-Requested-With"] = "XMLHttpRequest"
        
        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            params = {
                "query": "{}",
                "limit": "100",  # 🔥 CORREGIDO: Aumentar límite para obtener todas las vacantes
                "ascending": "1",
                "page": "1",
                "byColumn": "1"
            }
            
            logger.info("Obteniendo datos de vacantes...")
            response = await client.get(VACANTES_URL, params=params)
            
            logger.info(f"Respuesta API vacantes - Status: {response.status_code}")
            
            if response.status_code in [401, 419, 403]:
                logger.warning(f"Error de autenticación detectado: {response.status_code}")
                session_timestamp = None
                raise HTTPException(status_code=response.status_code, detail="Sesión expirada")
            
            if response.status_code >= 400:
                logger.error(f"Error HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"Error decodificando JSON: {str(e)}")
                raise HTTPException(status_code=502, detail="Respuesta inválida del servidor")
            
            if isinstance(data, dict) and "data" in data:
                vacantes = data["data"]
            elif isinstance(data, list):
                vacantes = data
            else:
                logger.warning(f"Estructura de datos inesperada: {type(data)}")
                vacantes = []
            
            logger.info(f"Obtenidos {len(vacantes)} registros de vacantes")
            return vacantes
            
    except httpx.TimeoutException:
        logger.error("Timeout al obtener datos de vacantes")
        raise HTTPException(status_code=408, detail="Timeout al obtener datos del servidor")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inesperado obteniendo vacantes: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

async def get_encryption_token(student_id: str) -> str:
    """Obtener token encriptado para el estudiante"""
    global auth_cookies, csrf_token
    
    if not auth_cookies or is_session_expired():
        logger.info("Sesión expirada, reautenticando...")
        login_success = await login_to_cepreuna()
        if not login_success:
            raise HTTPException(status_code=401, detail="No se pudo autenticar")
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": f"{BASE_URL}/intranet/inscripcion/estudiante/lista",
            "Connection": "keep-alive",
            "Cookie": auth_cookies
        }
        
        if csrf_token:
            headers["X-CSRF-TOKEN"] = csrf_token
            headers["X-Requested-With"] = "XMLHttpRequest"
        
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            encrypt_url = f"{ENCRYPT_URL}{student_id}"
            logger.info(f"Obteniendo token desde: {encrypt_url}")
            
            response = await client.get(encrypt_url)
            
            if response.status_code in [401, 419, 403]:
                raise HTTPException(status_code=401, detail="Sesión expirada al obtener token")
            
            response.raise_for_status()
            
            try:
                data = response.json()
                if isinstance(data, dict) and "token" in data:
                    return data["token"]
                elif isinstance(data, str):
                    return data
                else:
                    raise HTTPException(status_code=502, detail="Formato de token inesperado")
            except json.JSONDecodeError:
                token = response.text.strip()
                if token:
                    return token
                else:
                    raise HTTPException(status_code=502, detail="Token vacío")
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo token: {str(e)}")
        raise HTTPException(status_code=500, detail="Error obteniendo token")

def find_student_by_dni(students: List[Dict], dni: str) -> Optional[Dict]:
    """Buscar estudiante por DNI"""
    dni = dni.strip()
    
    for student_record in students:
        if isinstance(student_record, dict):
            # Campos posibles
            possible_dni_fields = ['dni', 'documento', 'numero_documento', 'cedula']
            for field in possible_dni_fields:
                if field in student_record and str(student_record[field]).strip() == dni:
                    return student_record

            # Buscar dentro del objeto 'estudiante'
            if 'estudiante' in student_record and isinstance(student_record['estudiante'], dict):
                student_data = student_record['estudiante']
                if 'nro_documento' in student_data and str(student_data['nro_documento']).strip() == dni:
                    return student_record
            
            # Buscar en 'persona'
            if 'persona' in student_record and isinstance(student_record['persona'], dict):
                person_data = student_record['persona']
                for field in possible_dni_fields:
                    if field in person_data and str(person_data[field]).strip() == dni:
                        return student_record

    return None

def process_student_data(students: List[Dict]) -> Dict:
    """Procesar y agrupar datos de estudiantes"""
    
    stats = {
        "total": len(students),
        "por_area": defaultdict(int),
        "por_sede": defaultdict(int),
        "por_turno": defaultdict(int),
        "por_sede_turno": defaultdict(int),
        "detalle_completo": defaultdict(lambda: defaultdict(lambda: defaultdict(int))),
        "ultimo_update": datetime.now().isoformat()
    }
    
    logger.info(f"Procesando {len(students)} estudiantes...")
    
    for registro in students:
        try:
            area = "Sin área"
            sede = "Sin sede"
            turno = "Sin turno"
            
            if isinstance(registro, dict):
                if "area" in registro and isinstance(registro["area"], dict):
                    area = registro["area"].get("denominacion", "Sin área")
                
                if "sede" in registro and isinstance(registro["sede"], dict):
                    sede = registro["sede"].get("denominacion", "Sin sede")
                
                if "turno" in registro and isinstance(registro["turno"], dict):
                    turno = registro["turno"].get("denominacion", "Sin turno")
            
            # Incrementar contadores
            stats["por_area"][area] += 1
            stats["por_sede"][sede] += 1
            stats["por_turno"][turno] += 1
            stats["por_sede_turno"][f"{sede} - {turno}"] += 1
            stats["detalle_completo"][area][sede][turno] += 1
            
        except Exception as e:
            logger.warning(f"Error procesando registro: {str(e)}")
            continue
    
    # Convertir defaultdict a dict normal
    return {
        "total": stats["total"],
        "por_area": dict(stats["por_area"]),
        "por_sede": dict(stats["por_sede"]),
        "por_turno": dict(stats["por_turno"]),
        "por_sede_turno": dict(stats["por_sede_turno"]),
        "detalle_completo": {
            area: {
                sede: dict(turnos)
                for sede, turnos in sedes.items()
            }
            for area, sedes in stats["detalle_completo"].items()
        },
        "ultimo_update": stats["ultimo_update"]
    }

# 🔥 NUEVA FUNCIÓN: Procesar datos de vacantes
def process_vacantes_data(vacantes: List[Dict]) -> Dict:
    """Procesar y agrupar datos de vacantes"""
    
    stats = {
        "total": 0,
        "por_area": defaultdict(int),
        "por_sede": defaultdict(int),
        "por_turno": defaultdict(int),
        "por_sede_turno": defaultdict(int),
        "detalle_completo": defaultdict(lambda: defaultdict(lambda: defaultdict(int))),
        "ultimo_update": datetime.now().isoformat()
    }
    
    logger.info(f"Procesando {len(vacantes)} registros de vacantes...")
    
    for registro in vacantes:
        try:
            area = "Sin área"
            sede = "Sin sede"
            turno = "Sin turno"
            cantidad = 0
            
            if isinstance(registro, dict):
                # Obtener cantidad de vacantes
                cantidad = int(registro.get("cantidad", 0))
                
                # Procesar área
                if "area" in registro and isinstance(registro["area"], dict):
                    area = registro["area"].get("denominacion", "Sin área")
                
                # Procesar sede
                if "sede" in registro and isinstance(registro["sede"], dict):
                    sede = registro["sede"].get("denominacion", "Sin sede")
                
                # Procesar turno
                if "turno" in registro and isinstance(registro["turno"], dict):
                    turno = registro["turno"].get("denominacion", "Sin turno")
            
            # Solo procesar si hay cantidad válida
            if cantidad > 0:
                # Incrementar contadores con la cantidad
                stats["total"] += cantidad
                stats["por_area"][area] += cantidad
                stats["por_sede"][sede] += cantidad
                stats["por_turno"][turno] += cantidad
                stats["por_sede_turno"][f"{sede} - {turno}"] += cantidad
                stats["detalle_completo"][area][sede][turno] = cantidad  # Asignar directamente, no sumar
                
                logger.debug(f"Procesado: {area} - {sede} - {turno}: {cantidad} vacantes")
            
        except Exception as e:
            logger.warning(f"Error procesando registro de vacante: {str(e)}")
            continue
    
    # Convertir defaultdict a dict normal
    result = {
        "total": stats["total"],
        "por_area": dict(stats["por_area"]),
        "por_sede": dict(stats["por_sede"]),
        "por_turno": dict(stats["por_turno"]),
        "por_sede_turno": dict(stats["por_sede_turno"]),
        "detalle_completo": {
            area: {
                sede: dict(turnos)
                for sede, turnos in sedes.items()
            }
            for area, sedes in stats["detalle_completo"].items()
        },
        "ultimo_update": stats["ultimo_update"]
    }
    
    logger.info(f"Resultado del procesamiento de vacantes: {stats['total']} vacantes totales")
    logger.info(f"Por área: {dict(stats['por_area'])}")
    logger.info(f"Por sede: {dict(stats['por_sede'])}")
    
    return result

def is_cache_valid() -> bool:
    """Verificar si el cache sigue siendo válido"""
    if not cached_data or not cache_timestamp:
        return False
    
    time_diff = (datetime.now() - cache_timestamp).total_seconds()
    return time_diff < CACHE_DURATION

# 🔥 ENDPOINTS DE LA API

@app.get("/api")
async def root_api():
    """Endpoint de prueba para la API"""
    return {"message": "API CEPREUNA funcionando correctamente"}

# 🔥 NUEVO: Health check para UptimeRobot
@app.get("/api/health")
async def health_check():
    """Health check para UptimeRobot - mantiene la app activa"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "cepreuna-api",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check_alt():
    """Health check alternativo"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# HEAD para /api/health
@app.head("/api/health")
async def health_check_head():
    """Respuesta vacía para UptimeRobot (HEAD)"""
    return Response(status_code=200)

# HEAD para /health
@app.head("/health")
async def health_check_alt_head():
    """Respuesta vacía para UptimeRobot (HEAD)"""
    return Response(status_code=200)

@app.get("/api/estudiantes/estadisticas", response_model=EstudianteStats)
async def get_student_statistics():
    """Obtener estadísticas de estudiantes con cache"""
    global cached_data, cache_timestamp
    
    try:
        # Verificar cache
        if is_cache_valid():
            logger.info("Devolviendo datos desde cache")
            return cached_data
        
        # Obtener datos frescos
        logger.info("Obteniendo datos frescos...")
        students = await fetch_student_data_with_retry()
        
        if not students:
            logger.warning("No se encontraron datos de estudiantes")
            empty_stats = {
                "total": 0,
                "por_area": {},
                "por_sede": {},
                "por_turno": {},
                "por_sede_turno": {},
                "detalle_completo": {},
                "ultimo_update": datetime.now().isoformat()
            }
            return empty_stats
        
        # Procesar datos
        stats = process_student_data(students)
        
        # Actualizar cache
        cached_data = stats
        cache_timestamp = datetime.now()
        
        logger.info(f"Datos procesados: {stats['total']} estudiantes")
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_student_statistics: {str(e)}")
        cached_data = None
        cache_timestamp = None
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# 🔥 NUEVO ENDPOINT: Estadísticas de vacantes
@app.get("/api/vacantes/estadisticas", response_model=VacantesStats)
async def get_vacantes_statistics():
    """Obtener estadísticas de vacantes con cache"""
    global cached_vacantes_data, vacantes_cache_timestamp
    
    try:
        # Verificar cache de vacantes
        if is_vacantes_cache_valid():
            logger.info("Devolviendo datos de vacantes desde cache")
            return cached_vacantes_data
        
        # Obtener datos frescos de vacantes
        logger.info("Obteniendo datos frescos de vacantes...")
        vacantes = await fetch_vacantes_data_with_retry()
        
        if not vacantes:
            logger.warning("No se encontraron datos de vacantes")
            empty_stats = {
                "total": 0,
                "por_area": {},
                "por_sede": {},
                "por_turno": {},
                "por_sede_turno": {},
                "detalle_completo": {},
                "ultimo_update": datetime.now().isoformat()
            }
            return empty_stats
        
        # Procesar datos de vacantes
        stats = process_vacantes_data(vacantes)
        
        # Actualizar cache de vacantes
        cached_vacantes_data = stats
        vacantes_cache_timestamp = datetime.now()
        
        logger.info(f"Datos de vacantes procesados: {stats['total']} vacantes totales")
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_vacantes_statistics: {str(e)}")
        cached_vacantes_data = None
        vacantes_cache_timestamp = None
        raise HTTPException(status_code=500, detail="Error interno del servidor obteniendo vacantes")

@app.get("/api/estudiantes/completos")
async def get_complete_student_data():
    """Obtener datos completos de estudiantes"""
    try:
        students = await fetch_student_data_with_retry()
        return {
            "total": len(students),
            "data": students,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_complete_student_data: {str(e)}")
        raise HTTPException(status_code=500, detail="Error obteniendo datos completos")

# 🔥 NUEVO ENDPOINT: Datos completos de vacantes
@app.get("/api/vacantes/completos")
async def get_complete_vacantes_data():
    """Obtener datos completos de vacantes"""
    try:
        vacantes = await fetch_vacantes_data_with_retry()
        return {
            "total": len(vacantes),
            "data": vacantes,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_complete_vacantes_data: {str(e)}")
        raise HTTPException(status_code=500, detail="Error obteniendo datos completos de vacantes")

# 🔥 NUEVO ENDPOINT: Debug para verificar estructura de datos
@app.get("/api/debug/vacantes")
async def debug_vacantes_data():
    """Endpoint para debug - verificar estructura de datos de vacantes"""
    try:
        vacantes = await fetch_vacantes_data_with_retry()
        
        # Tomar los primeros 3 registros para inspección
        sample_data = vacantes[:3] if len(vacantes) > 3 else vacantes
        
        # Procesar datos para ver el resultado
        processed = process_vacantes_data(vacantes)
        
        return {
            "raw_count": len(vacantes),
            "sample_raw_data": sample_data,
            "processed_stats": processed,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error en debug_vacantes_data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error en debug: {str(e)}")

@app.post("/api/estudiantes/ficha", response_model=FichaResponse)
async def get_student_ficha(dni_request: DNIRequest):
    """Obtener URL de descarga de ficha de inscripción por DNI"""
    try:
        dni = dni_request.dni.strip()
        
        if not dni:
            raise HTTPException(status_code=400, detail="DNI es requerido")
        
        if not re.match(r'^\d{8}$', dni):
            raise HTTPException(status_code=400, detail="DNI debe tener 8 dígitos")
        
        logger.info(f"Buscando estudiante con DNI: {dni}")
        
        students = await fetch_student_data_with_retry()
        
        if not students:
            raise HTTPException(status_code=404, detail="No se encontraron datos de estudiantes")
        
        student = find_student_by_dni(students, dni)
        
        if not student:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado")
        
        # Extraer ID del estudiante
        student_id = None
        if 'id' in student:
            student_id = str(student['id'])
        elif 'estudiante_id' in student:
            student_id = str(student['estudiante_id'])
        else:
            raise HTTPException(status_code=400, detail="No se pudo obtener el ID del estudiante")
        
        logger.info(f"Estudiante encontrado con ID: {student_id}")
        
        token = await get_encryption_token(student_id)
        
        if not token:
            raise HTTPException(status_code=500, detail="No se pudo obtener el token")
        
        download_url = f"{DOWNLOAD_URL}/{token}"
        
        logger.info(f"URL de descarga generada: {download_url}")
        
        return FichaResponse(
            download_url=download_url,
            estudiante=student,
            token=token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_student_ficha: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.post("/api/auth/login")
async def manual_login(login_data: LoginData):
    """Login manual"""
    global CEPREUNA_EMAIL, CEPREUNA_PASSWORD, auth_cookies, csrf_token, session_timestamp
    
    CEPREUNA_EMAIL = login_data.email
    CEPREUNA_PASSWORD = login_data.password
    
    auth_cookies = None
    csrf_token = None
    session_timestamp = None
    
    success = await login_to_cepreuna()
    if success:
        return {"message": "Login exitoso", "timestamp": session_timestamp.isoformat() if session_timestamp else None}
    else:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

@app.delete("/api/cache")
async def clear_cache():
    """Limpiar cache y sesión"""
    global cached_data, cache_timestamp, auth_cookies, csrf_token, session_timestamp
    global cached_vacantes_data, vacantes_cache_timestamp  # 🔥 NUEVO: Limpiar cache de vacantes
    
    cached_data = None
    cache_timestamp = None
    cached_vacantes_data = None  # 🔥 NUEVO
    vacantes_cache_timestamp = None  # 🔥 NUEVO
    auth_cookies = None
    csrf_token = None
    session_timestamp = None
    return {"message": "Cache y sesión limpiados"}

@app.get("/api/status")
async def get_status():
    """Estado detallado del sistema"""
    return {
        "status": "online",
        "cache_valid": is_cache_valid(),
        "vacantes_cache_valid": is_vacantes_cache_valid(),  # 🔥 NUEVO
        "authenticated": bool(auth_cookies),
        "session_expired": is_session_expired(),
        "has_csrf_token": bool(csrf_token),
        "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
        "vacantes_cache_timestamp": vacantes_cache_timestamp.isoformat() if vacantes_cache_timestamp else None,  # 🔥 NUEVO
        "session_timestamp": session_timestamp.isoformat() if session_timestamp else None,
        "cache_duration_seconds": CACHE_DURATION,
        "session_duration_seconds": SESSION_DURATION,
        "environment_vars": {
            "has_email": bool(CEPREUNA_EMAIL),
            "has_password": bool(CEPREUNA_PASSWORD),
            "base_url": BASE_URL,
            "vacantes_url": VACANTES_URL  # 🔥 NUEVO
        }
    }

# 🔥 SERVIR ARCHIVOS ESTÁTICOS DE REACT
# Verificar si existe la carpeta build
if os.path.exists("build"):
    # Servir archivos estáticos
    app.mount("/static", StaticFiles(directory="build/static"), name="static")
    
    # Servir archivos de la raíz (favicon, manifest, etc.)
    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse("build/favicon.ico")
    
    @app.get("/manifest.json")
    async def manifest():
        return FileResponse("build/manifest.json")
    
    @app.get("/robots.txt")
    async def robots():
        return FileResponse("build/robots.txt")
    
    # Servir la aplicación React para todas las demás rutas
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        """Servir la aplicación React"""
        # Si es una ruta de API, no interceptar
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        
        # Verificar si existe el archivo
        file_path = os.path.join("build", full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        
        # Si no existe, servir index.html (para routing de React)
        return FileResponse("build/index.html")
    
    # Root endpoint para servir React
    @app.get("/")
    async def root():
        """Servir la página principal de React"""
        return FileResponse("build/index.html")
else:
    # Si no existe build, servir mensaje de error
    @app.get("/")
    async def root():
        return {"message": "React app no compilado. Ejecuta 'npm run build'"}
    
    logger.warning("❌ Carpeta 'build' no encontrada. El frontend no estará disponible.")

@app.post("/api/auth/login")
async def manual_login(login_data: LoginData):
    """Login manual"""
    global CEPREUNA_EMAIL, CEPREUNA_PASSWORD, auth_cookies, csrf_token, session_timestamp
    
    CEPREUNA_EMAIL = login_data.email
    CEPREUNA_PASSWORD = login_data.password
    
    auth_cookies = None
    csrf_token = None
    session_timestamp = None
    
    success = await login_to_cepreuna()
    if success:
        return {"message": "Login exitoso", "timestamp": session_timestamp.isoformat() if session_timestamp else None}
    else:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

@app.delete("/api/cache")
async def clear_cache():
    """Limpiar cache y sesión"""
    global cached_data, cache_timestamp, auth_cookies, csrf_token, session_timestamp
    global cached_vacantes_data, vacantes_cache_timestamp  # 🔥 NUEVO: Limpiar cache de vacantes
    
    cached_data = None
    cache_timestamp = None
    cached_vacantes_data = None  # 🔥 NUEVO
    vacantes_cache_timestamp = None  # 🔥 NUEVO
    auth_cookies = None
    csrf_token = None
    session_timestamp = None
    return {"message": "Cache y sesión limpiados"}

@app.get("/api/status")
async def get_status():
    """Estado detallado del sistema"""
    return {
        "status": "online",
        "cache_valid": is_cache_valid(),
        "vacantes_cache_valid": is_vacantes_cache_valid(),  # 🔥 NUEVO
        "authenticated": bool(auth_cookies),
        "session_expired": is_session_expired(),
        "has_csrf_token": bool(csrf_token),
        "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None,
        "vacantes_cache_timestamp": vacantes_cache_timestamp.isoformat() if vacantes_cache_timestamp else None,  # 🔥 NUEVO
        "session_timestamp": session_timestamp.isoformat() if session_timestamp else None,
        "cache_duration_seconds": CACHE_DURATION,
        "session_duration_seconds": SESSION_DURATION,
        "environment_vars": {
            "has_email": bool(CEPREUNA_EMAIL),
            "has_password": bool(CEPREUNA_PASSWORD),
            "base_url": BASE_URL,
            "vacantes_url": VACANTES_URL  # 🔥 NUEVO
        }
    }

# 🔥 SERVIR ARCHIVOS ESTÁTICOS DE REACT
# Verificar si existe la carpeta build
if os.path.exists("build"):
    # Servir archivos estáticos
    app.mount("/static", StaticFiles(directory="build/static"), name="static")
    
    # Servir archivos de la raíz (favicon, manifest, etc.)
    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse("build/favicon.ico")
    
    @app.get("/manifest.json")
    async def manifest():
        return FileResponse("build/manifest.json")
    
    @app.get("/robots.txt")
    async def robots():
        return FileResponse("build/robots.txt")
    
    # Servir la aplicación React para todas las demás rutas
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        """Servir la aplicación React"""
        # Si es una ruta de API, no interceptar
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        
        # Verificar si existe el archivo
        file_path = os.path.join("build", full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        
        # Si no existe, servir index.html (para routing de React)
        return FileResponse("build/index.html")
    
    # Root endpoint para servir React
    @app.get("/")
    async def root():
        """Servir la página principal de React"""
        return FileResponse("build/index.html")
else:
    # Si no existe build, servir mensaje de error
    @app.get("/")
    async def root():
        return {"message": "React app no compilado. Ejecuta 'npm run build'"}
    
    logger.warning("❌ Carpeta 'build' no encontrada. El frontend no estará disponible.")

# 🔥 IMPORTANTE: Puerto dinámico para Render
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    logger.info(f"🚀 Iniciando servidor en {host}:{port}")
    logger.info(f"📧 Email configurado: {'✅' if CEPREUNA_EMAIL else '❌'}")
    logger.info(f"🔑 Password configurado: {'✅' if CEPREUNA_PASSWORD else '❌'}")
    logger.info(f"🏫 URL Vacantes: {VACANTES_URL}")  # 🔥 NUEVO
    
    uvicorn.run(app, host=host, port=port)