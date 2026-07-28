"""
Radar - Fingerprint Engine v1
Ticket 003: Sistema que evitará duplicados antes de scrapers completos

Objetivo: Identificar cuándo dos oportunidades son la misma convocatoria,
aunque vengan de distintas fuentes o tengan pequeñas diferencias de formato.

API Pública Estable (congelada desde v1):
    engine = FingerprintEngine()
    fp = engine.generate(opportunity)
    duplicate = engine.is_duplicate(fp, database)
    similarity = engine.compare(fp1, fp2)

Diseño:
- Core completamente agnóstico, sin reglas de organizaciones específicas
- Solo usa info estable: URL normalizada, Org, Título normalizado, Deadline, Tipo, País
- No usa premios, descripción, IA, scoring, etiquetas
- Normalización independiente y testeable
- Dos niveles: exacta (hash idéntico) y aproximada (RapidFuzz)
- Preparado para embeddings futuros sin romper API (metadata field)

Version fingerprint: v1 - interfaz congelada
"""
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from pathlib import Path
import datetime

# Optional deps
try:
    from unidecode import unidecode
    HAS_UNIDECODE = True
except ImportError:
    HAS_UNIDECODE = False
    unidecode = None

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    fuzz = None

try:
    from dateutil import parser as date_parser
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False
    date_parser = None

# Tracking params to remove for URL normalization
TRACKING_PARAMS = {
    # UTM
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_reader", "utm_viz_id", "utm_pubreferrer", "utm_swu",
    "utm_brand", "utm_cid", "utm_audience",
    # Click IDs
    "gclid", "gclsrc", "dclid", "fbclid", "igshid", "wbraid", "gbraid",
    "msclkid", "mc_cid", "mc_eid",
    # Analytics
    "_ga", "_gl", "_hsenc", "_hsmi", "hsCtaTracking", "hsCta2Tracking",
    "hsa_acc", "hsa_cam", "hsa_grp", "hsa_ad", "hsa_src", "hsa_tgt",
    "hsa_kw", "hsa_mt", "hsa_net", "hsa_ver",
    "srsltid", "_fbp", "ref", "ref_src", "ref_url",
}

# Prefixes that should be stripped if param startswith
TRACKING_PREFIXES = ("utm_",)

# Caracteres invisibles: zero-width, BOM, NBSP variations
INVISIBLE_CHARS_PATTERN = re.compile(r'[\u200b\u200c\u200d\u2060\u180e\ufeff\u00a0]')

# Para hash agresivo
NON_ALPHANUM_PATTERN = re.compile(r'[^a-z0-9]')

# --- Funciones de Normalización Independientes (testeables individualmente) ---

def remove_invisible_chars(text: str) -> str:
    """
    Elimina caracteres invisibles: zero-width space, BOM, etc.
    Reemplaza NBSP con espacio normal.
    Testeable individualmente.
    """
    if not text:
        return ""
    # NBSP \xa0 -> espacio normal primero
    text = text.replace("\xa0", " ").replace("\u00a0", " ")
    # Remove zero-width and BOM
    text = INVISIBLE_CHARS_PATTERN.sub("", text)
    return text

def normalize_whitespace(text: str) -> str:
    """
    Colapsa espacios duplicados, tabs, newlines a un solo espacio y trim.
    Testeable.
    """
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def to_lowercase(text: str) -> str:
    """Elimina mayúsculas/minúsculas -> lowercase. Testeable."""
    if not text:
        return ""
    return text.lower()

def remove_accents(text: str) -> str:
    """
    Remueve acentos usando unidecode si disponible, sino unicodedata.
    Testeable.
    """
    if not text:
        return ""
    if HAS_UNIDECODE and unidecode:
        return unidecode(text)
    # Fallback: NFD + strip combining chars
    nfkd = unicodedata.normalize('NFD', text)
    return ''.join([c for c in nfkd if not unicodedata.combining(c)])

def strip_tracking_params(url: str) -> str:
    """
    Elimina tracking parameters de URL (utm_*, fbclid, etc) y ordena query restante.
    Testeable independiente.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        
        qs = parse_qs(parsed.query, keep_blank_values=True)
        # Filtrar tracking params
        filtered_qs = {}
        for k, v in qs.items():
            k_lower = k.lower()
            if k_lower in TRACKING_PARAMS:
                continue
            if any(k_lower.startswith(prefix) for prefix in TRACKING_PREFIXES):
                continue
            filtered_qs[k] = v
        
        # Ordenar para determinismo
        sorted_qs = {}
        for k in sorted(filtered_qs.keys()):
            sorted_qs[k] = filtered_qs[k]
        
        new_query = urlencode(sorted_qs, doseq=True)
        # Reconstruir sin fragment
        new_parsed = parsed._replace(query=new_query, fragment="")
        return urlunparse(new_parsed)
    except Exception:
        # Si falla parse, devolver original sin tracking simple heuristic
        return url

def normalize_url(url: str) -> str:
    """
    Normalización completa de URL:
    - remove invisible, whitespace, lowercase host
    - remove www., default ports, trailing slash, fragment, tracking params, sort query
    Testeable.
    """
    if not url:
        return ""
    
    url = remove_invisible_chars(url)
    url = normalize_whitespace(url)
    
    if not url:
        return ""
    
    # Si no tiene scheme, intentar asumir https? Por ahora devolver lower stripped
    if not re.match(r'^https?://', url, re.IGNORECASE):
        return to_lowercase(url).strip()
    
    try:
        # Primero strip tracking
        url_no_tracking = strip_tracking_params(url)
        parsed = urlparse(url_no_tracking)
        
        # Lower scheme and netloc
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        
        # Remove www.
        if netloc.startswith("www."):
            netloc = netloc[4:]
        
        # Remove default ports
        if scheme == "http" and netloc.endswith(":80"):
            netloc = netloc[:-3]
        if scheme == "https" and netloc.endswith(":443"):
            netloc = netloc[:-4]
        
        # Path: remove trailing slash (unless root), lower? Path case-sensitive pero para dedup lower
        path = parsed.path
        if not path:
            path = "/"
        # Remove trailing slash if not root
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        # Lower path for dedup (evita /Competition vs /competition)
        path = path.lower()
        
        # Query ya está limpia y ordenada por strip_tracking_params, pero re-ordenar por si acaso
        query = parsed.query
        
        # Reconstruir sin fragment, sin params, sin default port
        normalized = urlunparse((
            scheme,
            netloc,
            path,
            parsed.params,
            query,
            ""  # fragment removed
        ))
        
        # Final lower for entire url? Ya hicimos host lower, pero path lower ya, mantener lower completo para consistencia
        normalized = normalized.lower()
        
        # Remove trailing slash again after lower
        if len(normalized) > len(scheme) + 3 + len(netloc) + 1 and normalized.endswith("/"):
            normalized = normalized.rstrip("/")
        
        return normalized
    
    except Exception:
        return to_lowercase(url).strip()

def normalize_title(title: str) -> str:
    """
    Normalización básica de título para comparación (preserva palabras):
    - invisible, whitespace, lower, accents
    Testeable.
    """
    if not title:
        return ""
    title = remove_invisible_chars(title)
    title = normalize_whitespace(title)
    title = to_lowercase(title)
    title = remove_accents(title)
    title = normalize_whitespace(title)  # otra vez por si accents introdujo espacios
    return title

def normalize_title_for_hash(title: str) -> str:
    """
    Normalización agresiva para hash: solo alfanumérico, sin espacios, truncado 60.
    Ej: "Posterheroes 2026!" -> "posterheroes2026"
    Testeable.
    """
    if not title:
        return ""
    # Primero normalización básica
    title = normalize_title(title)
    # Solo a-z0-9
    title = NON_ALPHANUM_PATTERN.sub("", title)
    # Truncar a 60 para evitar hashes muy distintos por títulos larguísimos
    return title[:60]

def normalize_org(org: str) -> str:
    """Normaliza organización slug/name: lower, invisible, whitespace, accents."""
    if not org:
        return ""
    org = remove_invisible_chars(org)
    org = normalize_whitespace(org)
    org = to_lowercase(org)
    org = remove_accents(org)
    # Para org, también quitar espacios para slug matching? Mantener con guión?
    # Para hash usamos solo alfanum sin espacios para que "AI Film Festival" == "ai-film-festival"
    org = NON_ALPHANUM_PATTERN.sub("", org)  # agresivo para matching org
    return org[:40]

def normalize_deadline(deadline: Any) -> str:
    """
    Normaliza deadline a YYYY-MM-DD string o "" si no existe.
    Acepta datetime, date, ISO string, timestamp.
    Testeable.
    """
    if not deadline:
        return ""
    
    # Si ya es datetime/date
    if isinstance(deadline, datetime.datetime):
        return deadline.date().isoformat()
    if isinstance(deadline, datetime.date):
        return deadline.isoformat()
    
    # Si es timestamp numérico
    if isinstance(deadline, (int, float)):
        try:
            dt = datetime.datetime.fromtimestamp(deadline)
            return dt.date().isoformat()
        except:
            return ""
    
    # Si es string, parsear
    if isinstance(deadline, str):
        deadline = remove_invisible_chars(deadline)
        deadline = normalize_whitespace(deadline)
        if not deadline or deadline.lower() in ("no_deadline", "none", "null", "tbd", "open"):
            return ""
        try:
            if HAS_DATEUTIL:
                dt = date_parser.parse(deadline, fuzzy=True)
                return dt.date().isoformat()
            else:
                # Try ISO
                dt = datetime.datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                return dt.date().isoformat()
        except Exception:
            # Si no parsea, intentar extraer YYYY-MM-DD con regex
            m = re.search(r'(\d{4})[-/\.](\d{1,2})[-/\.](\d{1,2})', deadline)
            if m:
                try:
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    return datetime.date(y, mo, d).isoformat()
                except:
                    pass
            return ""
    
    return ""

def normalize_opportunity_type(opp_type: str) -> str:
    """Normaliza tipo de oportunidad: contest, grant, etc."""
    if not opp_type:
        return "contest"  # default
    opp_type = remove_invisible_chars(opp_type)
    opp_type = normalize_whitespace(opp_type)
    opp_type = to_lowercase(opp_type)
    opp_type = remove_accents(opp_type)
    # Mapear variaciones comunes
    mapping = {
        "competition": "contest",
        "competencia": "contest",
        "concurso": "contest",
        "beca": "fellowship",
        "residencia": "residency",
        "festival": "festival",
        "beca": "grant",
        "grant": "grant",
    }
    return mapping.get(opp_type, opp_type)

def normalize_country(country: str) -> str:
    """Normaliza país: lower, accents, whitespace."""
    if not country:
        return ""
    country = remove_invisible_chars(country)
    country = normalize_whitespace(country)
    country = to_lowercase(country)
    country = remove_accents(country)
    # Para hash, quitar espacios y no alfanum
    country = NON_ALPHANUM_PATTERN.sub("", country)
    return country[:30]

# --- Dataclasses para API estable ---

@dataclass(frozen=True)
class Fingerprint:
    """
    Estructura congelada v1 - API estable.
    Contiene hash y componentes normalizados.
    metadata permite crecimiento futuro (embeddings, etc) sin romper API.
    """
    hash: str  # SHA256 truncated 16 chars - identificador estable
    normalized_url: str
    normalized_title: str  # para comparación (palabras preservadas)
    normalized_title_hash: str  # agresivo para hash
    normalized_org: str
    normalized_deadline: str  # YYYY-MM-DD o ""
    normalized_type: str
    normalized_country: str
    version: str = "v1"
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __str__(self):
        return f"Fingerprint(hash={self.hash}, org={self.normalized_org}, title={self.normalized_title[:30]}, deadline={self.normalized_deadline})"

@dataclass
class DuplicateResult:
    """Resultado de is_duplicate"""
    is_duplicate: bool
    level: str  # "exact", "approximate", "none"
    existing: Optional[Any]  # Fingerprint existente o DB row
    similarity: float  # 0-1
    matched_on: Dict[str, Any] = field(default_factory=dict)

# --- Engine Principal con API congelada ---

class FingerprintEngine:
    """
    Motor de fingerprint v1 - API congelada.
    Uso:
        engine = FingerprintEngine()
        fp = engine.generate(opportunity)
        duplicate = engine.is_duplicate(fp, database)
        similarity = engine.compare(fp1, fp2)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, title_threshold: float = None, deadline_delta_days: int = None):
        """
        config: dict o Config object opcional, lee thresholds de config.yaml
        title_threshold: override para similitud mínima (default 0.85)
        deadline_delta_days: override para delta deadline (default 15)
        """
        # Cargar thresholds desde config.yaml si disponible
        self.title_threshold = 0.85
        self.deadline_delta_days = 15
        self.version = "v1"
        
        try:
            if config is None:
                from core.config import get_config
                cfg = get_config()
                self.title_threshold = cfg.get("deduplication.title_similarity_threshold", 0.85)
                self.deadline_delta_days = cfg.get("deduplication.deadline_delta_days", 15)
                self.version = cfg.get("deduplication.fingerprint_version", "v1")
            elif isinstance(config, dict):
                self.title_threshold = config.get("title_similarity_threshold", config.get("deduplication", {}).get("title_similarity_threshold", 0.85))
                self.deadline_delta_days = config.get("deadline_delta_days", config.get("deduplication", {}).get("deadline_delta_days", 15))
            else:
                # Config object
                self.title_threshold = config.get("deduplication.title_similarity_threshold", 0.85) if hasattr(config, 'get') else 0.85
                self.deadline_delta_days = config.get("deduplication.deadline_delta_days", 15) if hasattr(config, 'get') else 15
        except Exception:
            # Fallback a defaults si config no disponible
            pass
        
        # Overrides explícitos
        if title_threshold is not None:
            self.title_threshold = title_threshold
        if deadline_delta_days is not None:
            self.deadline_delta_days = deadline_delta_days
    
    # --- Métodos de normalización expuestos para testabilidad ---
    
    def normalize_url(self, url: str) -> str:
        return normalize_url(url)
    
    def normalize_title(self, title: str) -> str:
        return normalize_title(title)
    
    def normalize_title_for_hash(self, title: str) -> str:
        return normalize_title_for_hash(title)
    
    def normalize_org(self, org: str) -> str:
        return normalize_org(org)
    
    def normalize_deadline(self, deadline: Any) -> str:
        return normalize_deadline(deadline)
    
    def normalize_type(self, opp_type: str) -> str:
        return normalize_opportunity_type(opp_type)
    
    def normalize_country(self, country: str) -> str:
        return normalize_country(country)
    
    def remove_invisible_chars(self, text: str) -> str:
        return remove_invisible_chars(text)
    
    def normalize_whitespace(self, text: str) -> str:
        return normalize_whitespace(text)
    
    # --- API Principal ---
    
    def generate(self, opportunity: Union[Dict[str, Any], Any]) -> Fingerprint:
        """
        Genera fingerprint estable desde oportunidad.
        Acepta dict, NormalizedOpportunity, o cualquier objeto con atributos.
        
        Campos usados (solo info estable):
        - URL oficial: official_link, url, link
        - Organización: organization_slug, organizer_name, organization, org, org_slug
        - Título: title
        - Deadline: deadline, deadline_date, end_date, closing_date
        - Tipo: opportunity_type, type
        - País: country
        
        No usa: premios, descripción, scoring, etiquetas, IA.
        """
        # Extraer campos crudos
        raw_url = self._extract_field(opportunity, ["official_link", "url", "link", "source_url", "official_url"], "")
        raw_org = self._extract_field(opportunity, ["organization_slug", "organizer_name", "organization", "org", "org_slug", "organizer", "org_name"], "")
        raw_title = self._extract_field(opportunity, ["title", "name", "opportunity_title"], "")
        raw_deadline = self._extract_field(opportunity, ["deadline", "deadline_date", "end_date", "closing_date", "close_date", "due_date"], "")
        raw_type = self._extract_field(opportunity, ["opportunity_type", "type", "category"], "contest")
        raw_country = self._extract_field(opportunity, ["country", "pais", "location_country"], "")
        
        # Normalizar cada campo con funciones independientes
        norm_url = normalize_url(raw_url)
        norm_org = normalize_org(raw_org)
        norm_title = normalize_title(raw_title)
        norm_title_hash = normalize_title_for_hash(raw_title)
        norm_deadline = normalize_deadline(raw_deadline)
        norm_type = normalize_opportunity_type(raw_type)
        norm_country = normalize_country(raw_country)
        
        # Generar hash estable: SHA256 de componentes concatenados con |
        # Estructura congelada v1: org|title_hash|deadline|type|country|url
        # Orden fijo para estabilidad
        hash_input = "|".join([
            norm_org,
            norm_title_hash,
            norm_deadline,
            norm_type,
            norm_country,
            norm_url
        ])
        hash_full = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        hash_short = hash_full[:16]  # 16 chars suficiente, más legible
        
        return Fingerprint(
            hash=hash_short,
            normalized_url=norm_url,
            normalized_title=norm_title,
            normalized_title_hash=norm_title_hash,
            normalized_org=norm_org,
            normalized_deadline=norm_deadline,
            normalized_type=norm_type,
            normalized_country=norm_country,
            version=self.version,
            metadata={
                "hash_input": hash_input,
                "hash_full": hash_full,
                "raw": {
                    "url": raw_url,
                    "org": raw_org,
                    "title": raw_title,
                    "deadline": str(raw_deadline)[:30],
                    "type": raw_type,
                    "country": raw_country
                }
            }
        )
    
    def compare(self, fp1: Fingerprint, fp2: Fingerprint) -> float:
        """
        Compara dos fingerprints y retorna similitud 0-1.
        
        Nivel 1: Exacta -> hash idéntico => 1.0
        Nivel 2: Aproximada -> RapidFuzz title similarity + org + deadline proximity
        
        Preparado para crecimiento futuro (embeddings) sin modificar API.
        """
        if not isinstance(fp1, Fingerprint) or not isinstance(fp2, Fingerprint):
            raise ValueError("compare() requiere Fingerprint objects")
        
        # Nivel 1: Exacta
        if fp1.hash == fp2.hash:
            return 1.0
        
        # Si orgs diferentes y ambos no vacíos, no pueden ser duplicados exactos
        # Pero para similitud, devolvemos bajo
        org_match = 1.0 if fp1.normalized_org == fp2.normalized_org else 0.0
        if fp1.normalized_org and fp2.normalized_org and fp1.normalized_org != fp2.normalized_org:
            # Org diferente: incluso si título idéntico, max similitud 0.3 (evita falsos positivos)
            title_sim = self._title_similarity(fp1.normalized_title, fp2.normalized_title)
            return title_sim * 0.3
        
        # Title similarity con RapidFuzz (core de nivel 2)
        title_sim = self._title_similarity(fp1.normalized_title, fp2.normalized_title)
        
        # Deadline match
        deadline_match = self._deadline_similarity(fp1.normalized_deadline, fp2.normalized_deadline)
        
        # Type y country
        type_match = 1.0 if fp1.normalized_type == fp2.normalized_type else 0.0
        country_match = 1.0 if fp1.normalized_country == fp2.normalized_country else (0.5 if not fp1.normalized_country or not fp2.normalized_country else 0.0)
        
        # URL exact match boost
        url_match = 1.0 if fp1.normalized_url and fp1.normalized_url == fp2.normalized_url else 0.0
        
        # Si URL exacta y org misma => casi duplicado aunque título difiera ligeramente
        if url_match == 1.0 and org_match == 1.0:
            return max(0.95, title_sim)
        
        # Weighted average para caso general org misma
        # Título 70%, deadline 15%, type 10%, country 5%
        overall = (
            title_sim * 0.70 +
            deadline_match * 0.15 +
            type_match * 0.10 +
            country_match * 0.05
        )
        
        return round(overall, 4)
    
    def is_duplicate(self, fp: Fingerprint, database: Optional[Any] = None) -> Optional[DuplicateResult]:
        """
        Determina si fingerprint ya existe en database.
        
        database puede ser:
        - None: no busca, retorna None
        - List[Fingerprint] | List[dict] | List[str]: busca en memoria
        - RadarDB | sqlite3.Connection | Path | str (db path): busca en SQLite
        - Cualquier objeto con método que retorne oportunidades
        
        Retorna:
        - None si no es duplicado
        - DuplicateResult si es duplicado (exact o approximate)
        
        Dos niveles:
        Level 1: fingerprint idéntico (hash)
        Level 2: org igual + title similarity >= threshold + deadline dentro de delta
        """
        if not isinstance(fp, Fingerprint):
            raise ValueError("is_duplicate() requiere Fingerprint object")
        
        if database is None:
            return None
        
        # Caso lista en memoria
        if isinstance(database, list):
            return self._is_duplicate_in_list(fp, database)
        
        # Caso RadarDB o DB path
        try:
            # Si es Path o str a DB sqlite
            if isinstance(database, (str, Path)):
                from core.db import get_db
                db = get_db(Path(database))
                return self._is_duplicate_in_db(fp, db)
            
            # Si tiene método connect (RadarDB)
            if hasattr(database, 'connect'):
                return self._is_duplicate_in_db(fp, database)
            
            # Si es sqlite3 connection
            if hasattr(database, 'execute'):
                return self._is_duplicate_in_sqlite_conn(fp, database)
            
        except Exception as e:
            # Fallback: intentar como lista si tiene __iter__
            try:
                if hasattr(database, '__iter__'):
                    return self._is_duplicate_in_list(fp, list(database))
            except:
                pass
        
        return None
    
    # --- Métodos internos helpers ---
    
    def _extract_field(self, obj: Any, keys: List[str], default: Any = "") -> Any:
        """Extrae campo de dict u objeto probando varias keys."""
        if obj is None:
            return default
        
        # Si es dict
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] not in (None, ""):
                    return obj[k]
                # Probar variaciones lower
                for actual_k in obj.keys():
                    if actual_k.lower() == k.lower() and obj[actual_k] not in (None, ""):
                        return obj[actual_k]
            return default
        
        # Si es objeto con atributos
        for k in keys:
            if hasattr(obj, k):
                val = getattr(obj, k)
                if val not in (None, ""):
                    return val
        
        # Si tiene dict interno (dataclass)
        if hasattr(obj, '__dict__'):
            d = obj.__dict__
            for k in keys:
                if k in d and d[k] not in (None, ""):
                    return d[k]
        
        return default
    
    def _title_similarity(self, t1: str, t2: str) -> float:
        """Calcula similitud de títulos 0-1 usando RapidFuzz o fallback."""
        if not t1 and not t2:
            return 1.0
        if not t1 or not t2:
            return 0.0
        
        if HAS_RAPIDFUZZ and fuzz:
            # Usar ratio + token_sort_ratio para casos como "Posterheroes 2026" vs "Poster Heroes 2026"
            try:
                ratio = fuzz.ratio(t1, t2) / 100.0
                token_ratio = fuzz.token_sort_ratio(t1, t2) / 100.0
                # Tomar max para capturar reordenamientos y espacios
                return max(ratio, token_ratio)
            except Exception:
                pass
        
        # Fallback sin rapidfuzz: Jaccard de bigramas simple
        try:
            # Simple: si uno contiene al otro
            if t1 in t2 or t2 in t1:
                return 0.9
            # Jaccard de palabras
            set1 = set(t1.split())
            set2 = set(t2.split())
            if not set1 and not set2:
                return 1.0
            if not set1 or not set2:
                return 0.0
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            return intersection / union if union else 0.0
        except Exception:
            return 0.0
    
    def _deadline_similarity(self, d1: str, d2: str) -> float:
        """Similitud de deadlines: 1.0 si mismo día, 0.8 si dentro de delta, etc."""
        if not d1 and not d2:
            return 1.0  # ambos sin deadline => match neutral
        if not d1 or not d2:
            return 0.5  # uno sin deadline => neutral medio
        
        if d1 == d2:
            return 1.0
        
        try:
            date1 = datetime.date.fromisoformat(d1)
            date2 = datetime.date.fromisoformat(d2)
            delta = abs((date1 - date2).days)
            if delta == 0:
                return 1.0
            if delta <= self.deadline_delta_days:
                # Dentro de delta: 0.8 si <= delta, decae
                return max(0.5, 1.0 - (delta / (self.deadline_delta_days * 2)))
            else:
                return max(0.0, 0.5 - (delta / 100.0))
        except Exception:
            # Si no parsea, comparar strings
            return 1.0 if d1 == d2 else 0.0
    
    def _is_duplicate_in_list(self, fp: Fingerprint, existing_list: List[Any]) -> Optional[DuplicateResult]:
        """Busca duplicado en lista en memoria."""
        for existing in existing_list:
            # Normalizar existing a Fingerprint si es necesario
            existing_fp = None
            if isinstance(existing, Fingerprint):
                existing_fp = existing
            elif isinstance(existing, str):
                # Si es string hash
                if existing == fp.hash:
                    return DuplicateResult(
                        is_duplicate=True,
                        level="exact",
                        existing=existing,
                        similarity=1.0,
                        matched_on={"hash": fp.hash}
                    )
                continue
            elif isinstance(existing, dict):
                # Si es dict con hash o fingerprint
                if existing.get("hash") == fp.hash or existing.get("fingerprint_hash") == fp.hash:
                    return DuplicateResult(
                        is_duplicate=True,
                        level="exact",
                        existing=existing,
                        similarity=1.0,
                        matched_on={"hash": fp.hash}
                    )
                # Intentar generar fingerprint del dict para comparar
                try:
                    existing_fp = self.generate(existing)
                except:
                    continue
            else:
                try:
                    existing_fp = self.generate(existing)
                except:
                    continue
            
            if existing_fp:
                # Level 1: exact hash
                if existing_fp.hash == fp.hash:
                    return DuplicateResult(
                        is_duplicate=True,
                        level="exact",
                        existing=existing_fp,
                        similarity=1.0,
                        matched_on={"hash": fp.hash}
                    )
                
                # Level 2: approximate
                sim = self.compare(fp, existing_fp)
                if sim >= self.title_threshold and fp.normalized_org == existing_fp.normalized_org:
                    # Verificar deadline delta también para approximate
                    if self._deadlines_within_delta(fp.normalized_deadline, existing_fp.normalized_deadline):
                        return DuplicateResult(
                            is_duplicate=True,
                            level="approximate",
                            existing=existing_fp,
                            similarity=sim,
                            matched_on={
                                "title_similarity": sim,
                                "org": fp.normalized_org,
                                "deadline1": fp.normalized_deadline,
                                "deadline2": existing_fp.normalized_deadline
                            }
                        )
        
        return None
    
    def _is_duplicate_in_db(self, fp: Fingerprint, db) -> Optional[DuplicateResult]:
        """Busca duplicado en RadarDB."""
        try:
            with db.connect() as conn:
                return self._is_duplicate_in_sqlite_conn(fp, conn)
        except Exception as e:
            # Fallback
            return None
    
    def _is_duplicate_in_sqlite_conn(self, fp: Fingerprint, conn) -> Optional[DuplicateResult]:
        """Busca duplicado en sqlite connection."""
        try:
            # Level 1: exact hash match
            cur = conn.execute("SELECT * FROM opportunities WHERE fingerprint_hash = ?", (fp.hash,))
            row = cur.fetchone()
            if row:
                # Convertir row a dict
                existing_dict = dict(row) if hasattr(row, 'keys') else dict(row)
                return DuplicateResult(
                    is_duplicate=True,
                    level="exact",
                    existing=existing_dict,
                    similarity=1.0,
                    matched_on={"fingerprint_hash": fp.hash}
                )
            
            # Level 2: approximate - buscar candidatas con misma org y deadline cercano
            # Para no traer toda la tabla, filtrar por org y deadline
            # Si no tiene org, buscar todas recientes
            candidates = []
            if fp.normalized_org:
                # Buscar por organization slug? Necesitamos mapear org normalized a id
                # Simplificación: buscar oportunidades cuya organization slug normalizado coincida
                # Asumimos que opportunities tiene organization_id y podemos join a organizations slug
                try:
                    # Intentar query con join
                    cur = conn.execute("""
                        SELECT o.*, org.slug as org_slug 
                        FROM opportunities o 
                        JOIN organizations org ON o.organization_id = org.id
                    """)
                    all_opps = cur.fetchall()
                    for r in all_opps:
                        d = dict(r)
                        # Generar fingerprint de la existente para comparar (usando datos de DB)
                        try:
                            existing_fp = self.generate({
                                "title": d.get("title",""),
                                "official_link": d.get("official_link",""),
                                "organization_slug": d.get("org_slug",""),
                                "deadline": d.get("deadline",""),
                                "opportunity_type": d.get("category","contest"),
                                "country": d.get("country","")
                            })
                            # Solo considerar misma org
                            if existing_fp.normalized_org == fp.normalized_org:
                                candidates.append((d, existing_fp))
                        except:
                            continue
                except Exception:
                    # Fallback sin join
                    cur = conn.execute("SELECT * FROM opportunities")
                    for r in cur.fetchall():
                        d = dict(r)
                        try:
                            existing_fp = self.generate(d)
                            if existing_fp.normalized_org == fp.normalized_org:
                                candidates.append((d, existing_fp))
                        except:
                            continue
            else:
                # Sin org, no hacer approximate exhaustivo (evita falso positivo)
                return None
            
            # Comparar candidatas
            for db_row, existing_fp in candidates:
                sim = self.compare(fp, existing_fp)
                if sim >= self.title_threshold:
                    if self._deadlines_within_delta(fp.normalized_deadline, existing_fp.normalized_deadline):
                        return DuplicateResult(
                            is_duplicate=True,
                            level="approximate",
                            existing=db_row,
                            similarity=sim,
                            matched_on={
                                "title_similarity": sim,
                                "org": fp.normalized_org
                            }
                        )
            
            return None
        
        except Exception as e:
            # Si tabla no existe, etc
            return None
    
    def _deadlines_within_delta(self, d1: str, d2: str) -> bool:
        """Verifica si dos deadlines están dentro de delta configurado, o uno vacío."""
        if not d1 or not d2:
            return True  # Si uno no tiene deadline, no penalizar
        try:
            date1 = datetime.date.fromisoformat(d1)
            date2 = datetime.date.fromisoformat(d2)
            delta = abs((date1 - date2).days)
            return delta <= self.deadline_delta_days
        except:
            # Si no parsea, asumir dentro si strings iguales o uno vacío
            return d1 == d2 or not d1 or not d2

# --- Funciones de conveniencia para API estable y tests ---

# Instancia global opcional para uso simple
_default_engine = None

def get_fingerprint_engine() -> FingerprintEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = FingerprintEngine()
    return _default_engine

# Funciones sueltas para backwards compat y testabilidad individual (estable)
def generate_fingerprint(opportunity: Any) -> Fingerprint:
    """Helper: genera fingerprint usando engine default."""
    return get_fingerprint_engine().generate(opportunity)

def compare_fingerprints(fp1: Fingerprint, fp2: Fingerprint) -> float:
    """Helper: compara dos fingerprints."""
    return get_fingerprint_engine().compare(fp1, fp2)
