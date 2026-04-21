import streamlit as st
import sqlite3
import networkx as nx
import streamlit.components.v1 as components
import hashlib
import requests
import os
import re
import json
from send_message import send_email
from dotenv import load_dotenv
import threading
from llm_chat import ask_llama_stream

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DB_PATH        = "school_map2120.db"
SVG_TEMPLATE   = "Floor{floor}_G.svg"


COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "_map_component")
os.makedirs(COMPONENT_DIR, exist_ok=True)


def _write_static_html(height_px: int = 660):
    """
    Записывает index.html один раз.
    Никакого SVG внутри — он придёт через props при каждом рендере.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: transparent; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }}

#map-wrap {{
  width: 100%;
  height: {height_px - 52}px;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid #ddd;
  background: #fff;
}}
#map-wrap svg {{ width: 100%; height: 100%; }}

/* Тексты SVG не кликабельны */
#map-wrap svg text,
#map-wrap svg tspan {{
  pointer-events: none !important;
  user-select: none;
}}

/* Кликабельные кабинеты */
#map-wrap svg [data-room] {{ cursor: pointer; transition: fill-opacity .15s; }}
#map-wrap svg [data-room]:hover {{ fill-opacity: .55 !important; }}

/* Попап */
#popup {{
  display: none; position: fixed; z-index: 9999;
  background: #fff; border: 1px solid #ddd; border-radius: 12px;
  padding: 14px 14px 8px;
  box-shadow: 0 8px 28px rgba(0,0,0,.18); min-width: 200px;
}}
#popup-title {{
  font-weight: 700; font-size: 14px; margin-bottom: 10px;
  color: #111; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 190px;
}}
#popup button {{
  display: block; width: 100%; margin-bottom: 7px;
  padding: 8px 12px; border: none; border-radius: 8px;
  cursor: pointer; font-size: 13px; text-align: left;
}}
#popup button:hover {{ opacity: .82; }}
#pbtn-from   {{ background: #4B57FF; color: #fff; }}
#pbtn-to     {{ background: #FF4B4B; color: #fff; }}
#pbtn-cancel {{ background: #f0f0f0; color: #444; }}

#btnSave {{
  margin-bottom: 8px; padding: 9px 20px;
  background: #FF4B4B; color: #fff;
  border: none; border-radius: 8px; cursor: pointer; font-size: 13px;
}}
</style>
</head>
<body>

<div id="popup">
  <div id="popup-title">—</div>
  <button id="pbtn-from">📍 Я здесь (старт)</button>
  <button id="pbtn-to">🎯 Сюда (финиш)</button>
  <button id="pbtn-cancel">✕ Отмена</button>
</div>

<button id="btnSave">💾 Сохранить PNG</button>
<div id="map-wrap"></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
<script>
// ── Официальный протокол Streamlit ───────────────────────────────
function sendToStreamlit(type, data) {{
  var msg = Object.assign({{ isStreamlitMessage: true, type: type }}, data);
  window.parent.postMessage(msg, "*");
}}
function setFrameHeight(h) {{
  sendToStreamlit("streamlit:setFrameHeight", {{ height: h }});
}}
function sendValue(value) {{
  sendToStreamlit("streamlit:setComponentValue", {{ value: value, dataType: "json" }});
}}

// ── Состояние ────────────────────────────────────────────────────
var LABEL_MAP = {{}};
var popup     = document.getElementById('popup');
var ptitle    = document.getElementById('popup-title');
var curLabel  = null;
var panZoomInstance = null;

function initPanZoom() {{
  var svgEl = document.querySelector('#map-wrap svg');
  if (!svgEl || typeof svgPanZoom === 'undefined') return;
  try {{
    if (panZoomInstance) panZoomInstance.destroy();
  }} catch (e) {{}}
  panZoomInstance = svgPanZoom(svgEl, {{
    zoomEnabled: true,
    controlIconsEnabled: true,
    fit: true,
    center: true,
    minZoom: 0.6,
    maxZoom: 15
  }});
}}

// ── Получение props от Python ────────────────────────────────────
// Streamlit вызывает этот обработчик при каждом рендере компонента,
// передавая все именованные аргументы: svg=, label_map=, show_icons=
window.addEventListener("message", function(event) {{
  if (!event.data || event.data.type !== "streamlit:render") return;

  var args = event.data.args || {{}};

  // Обновляем маппинг кабинетов
  var labelUpdated = false;
  if (args.label_map) {{
    try {{ LABEL_MAP = JSON.parse(args.label_map); }}
    catch(e) {{ LABEL_MAP = args.label_map; }}
    labelUpdated = true;
  }}

  // Обновляем SVG — маршрут всегда свежий
  var svgUpdated = false;
  if (args.svg) {{
    document.getElementById('map-wrap').innerHTML = args.svg;
    svgUpdated = true;
  }}

  if (svgUpdated || labelUpdated) {{
    applyClickHandlers();
    initPanZoom();
  }}

  // Иконки
  var icons = document.getElementById('icons');
  if (icons) {{
    icons.style.visibility = args.show_icons ? 'visible' : 'hidden';
    icons.style.display    = args.show_icons ? 'block'   : 'none';
  }}

  setFrameHeight(document.documentElement.clientHeight);
}});

// ── Назначаем обработчики кликов после обновления SVG ────────────
function applyClickHandlers() {{
  document.querySelectorAll('#map-wrap svg text, #map-wrap svg tspan').forEach(function(el) {{
    el.style.pointerEvents = 'none';
  }});
  document.querySelectorAll('#map-wrap svg rect, #map-wrap svg path').forEach(function(el) {{
    if (el.id && LABEL_MAP[el.id] !== undefined) {{
      el.setAttribute('data-room', el.id);
    }}
  }});
}}

// ── Попап ─────────────────────────────────────────────────────────
function openPopup(x, y, label) {{
  curLabel = label;
  ptitle.textContent = label;
  popup.style.display = 'block';
  var pw = 220, ph = 155;
  popup.style.left = Math.min(x + 10, window.innerWidth  - pw - 8) + 'px';
  popup.style.top  = Math.min(y + 10, window.innerHeight - ph - 8) + 'px';
}}
function closePopup() {{
  popup.style.display = 'none';
  curLabel = null;
}}

document.getElementById('map-wrap').addEventListener('click', function(e) {{
  var el = e.target.closest('[data-room]');
  if (!el) {{ closePopup(); return; }}
  e.stopPropagation();
  var label = LABEL_MAP[el.getAttribute('data-room')];
  if (label) openPopup(e.clientX, e.clientY, label);
}});

document.addEventListener('click', function(e) {{
  if (!popup.contains(e.target)) closePopup();
}});

document.getElementById('pbtn-from').addEventListener('click', function() {{
  if (!curLabel) return;
  var label = curLabel; closePopup();
  sendValue({{ action: 'from', label: label }});
}});
document.getElementById('pbtn-to').addEventListener('click', function() {{
  if (!curLabel) return;
  var label = curLabel; closePopup();
  sendValue({{ action: 'to', label: label }});
}});
document.getElementById('pbtn-cancel').addEventListener('click', closePopup);

// ── Сохранение PNG ────────────────────────────────────────────────
document.getElementById('btnSave').addEventListener('click', async function() {{
  var btn = document.getElementById('btnSave');
  if (typeof html2canvas === 'undefined') {{
    alert('Библиотека ещё загружается, подождите пару секунд'); return;
  }}
  btn.textContent = 'Обработка…'; btn.disabled = true;
  try {{
    var canvas = await html2canvas(document.getElementById('map-wrap'), {{
      scale: 2, useCORS: true, allowTaint: true,
      backgroundColor: '#fff', logging: false,
    }});
    var a = document.createElement('a');
    a.download = 'marshrut_2120.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
    btn.textContent = '✅ Готово';
  }} catch(err) {{
    alert('Ошибка: ' + err.message); btn.textContent = '❌ Ошибка';
  }} finally {{
    setTimeout(function() {{ btn.textContent = '💾 Сохранить PNG'; btn.disabled = false; }}, 2500);
  }}
}});

// Сигнал готовности — без него Streamlit не активирует компонент
sendToStreamlit("streamlit:componentReady", {{ apiVersion: 1 }});
</script>
</body>
</html>"""

    index_path = os.path.join(COMPONENT_DIR, "index.html")
    try:
        if open(index_path, encoding="utf-8").read() == html:
            return
    except FileNotFoundError:
        pass
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)


# Записываем статический HTML при старте
_write_static_html(height_px=720)

# Регистрируем компонент один раз
_svg_map_component = components.declare_component("svg_map", path=COMPONENT_DIR)


# ─────────────────────────── БД ──────────────────────────────────

def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def login_user(login, password):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT id, role, first_name, last_name FROM users WHERE login=? AND password=?",
                (login, hash_password(password)))
    row = cur.fetchone(); conn.close(); return row

def register_user(login, password, first_name, last_name, role="Ученик"):
    try:
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("INSERT INTO users (login, password, first_name, last_name, role) VALUES (?,?,?,?,?)",
                    (login, hash_password(password), first_name, last_name, role))
        conn.commit(); conn.close(); return True
    except: return False

def log_route(user_id, start, end, length):
    try:
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("INSERT INTO route_logs (user_id, from_point, to_point, length) VALUES (?,?,?,?)",
                    (user_id, start, end, length))
        conn.commit(); conn.close()
    except: pass

def get_teacher_telegram(person_name):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM teachers WHERE name=? OR full_name=?",
                (person_name, person_name))
    row = cur.fetchone(); conn.close()
    return row[0] if row else None

def send_telegram_message(chat_id, message):
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     params={"chat_id": chat_id, "text": message}, timeout=10)
    except: pass

def send_notifications_async(tid, message, email, email_message):
    """Отправляет все уведомления в фоне — не блокирует UI."""
    def _run():
        send_telegram_message(tid, message)
        try: send_email(email, email_message)
        except: pass
    threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────── Граф ────────────────────────────────

def load_data_from_db(db_path):
    conn = sqlite3.connect(db_path); cur = conn.cursor()
    cur.execute("SELECT id, x, y, floor, type, label, person FROM nodes")
    positions, floors, types, labels, categories = {}, {}, {}, {}, {}
    for node_id, x, y, floor, n_type, label, person in cur.fetchall():
        positions[node_id] = (x, y)
        floors[node_id]    = floor
        types[node_id]     = n_type or "regular"
        if label and person is not None:
            labels[label + f" {person}"] = node_id
        elif label:
            labels[label] = node_id
        if n_type:
            categories.setdefault(n_type.capitalize(), []).append(node_id)
    cur.execute("SELECT node_from, node_to, weight FROM edges")
    edges = [(u, v, float(w)) for u, v, w in cur.fetchall()]
    conn.close()
    return positions, floors, types, labels, edges, categories

@st.cache_resource
def build_graph():
    POS, FLOORS, TYPES, LABELS, EDGES, CATEGORIES = load_data_from_db(DB_PATH)
    G = nx.Graph()
    for node_id, pos in POS.items():
        G.add_node(node_id, pos=pos, floor=FLOORS[node_id], type=TYPES[node_id])
    G.add_weighted_edges_from(EDGES)
    return G, POS, LABELS, CATEGORIES

def resolve_selection(selection, labels, categories):
    if not selection: return []
    if selection in labels:     return [labels[selection]]
    if selection in categories: return categories[selection]
    return []

def filter_graph_by_mobility(G, mgn):
    forbidden = {"лестница", "staircase"} if mgn else {"лифт", "elevator"}
    allowed = [n for n, d in G.nodes(data=True)
               if str(d.get("type", "")).lower() not in forbidden]
    return G.subgraph(allowed).copy()

def restrict_to_single_floor(G, floor):
    return G.subgraph([n for n, d in G.nodes(data=True)
                       if d.get("floor") == floor]).copy()

def find_best_path(G, starts, targets, mgn):
    best_path, best_len = None, float("inf")
    base_G = filter_graph_by_mobility(G, mgn)
    for s in starts:
        for t in targets:
            if s not in base_G or t not in base_G: continue
            wG = base_G
            if G.nodes[s]["floor"] == G.nodes[t]["floor"]:
                wG = restrict_to_single_floor(base_G, G.nodes[s]["floor"])
            try:
                p = nx.dijkstra_path(wG, s, t, weight="weight")
                l = nx.path_weight(wG, p, "weight")
                if l < best_len: best_len, best_path = l, p
            except nx.NetworkXNoPath: pass
    return best_path


# ─────────────────────────── SVG label map ───────────────────────
SVG_RECT_TO_NUMBER = {
    "R106": "106", "R107": "107", "R108": "108", "R109": "109",
    "R110": "110", "R111": "111", "R112": "112", "R113": "113",
    "R114": "114", "R116": "116", "R117": "117", "R118": "118",
    "R119": "119", "R120": "120", "R121": "121", "R122": "122",
    "R123": "123", "R124": "124", "R125": "125", "R126": "126",
    "R127": "127",
    "R314": "314",
    "Canteen": "__canteen__",
    
    "R324": "324", "R323": "323", "R322": "322", "R321": "321",
    "R320": "320", "R319": "319", "R317": "317", "R316": "316",
    "R315": "315", "R313": "313", "R312": "312", "R311": "311",
    "R310": "310", "R309": "309", "R307": "307", "R306": "306",
    "R305": "305", "R304": "304", "R302": "302", "R301": "301",

    "R229": "229", "R228": "228", "R227": "227", "R226": "226",
    "R225": "225", "R223": "223", "R222": "222", "R221": "221",
    "R219": "219", "R218": "218", "R217": "217", "R214_2": "214_2",
    "R214_1": "214_1", "R213": "213", "R212": "212", "R211": "211",
    "R210": "210", "R209": "209", "R208": "208", "R207": "207",
    "R206": "206", "R205": "205", "R204": "204", "R203": "203",
    "R202": "202", "R201": "201",

    "R126": "126", "R125": "125", "R124": "124", "R122": "122",
    "R121": "121", "R114": "114", "R113": "113", "R112": "112",
    "R111": "111", "R110": "110", "R109": "109", "R108": "108",
    "R107": "107", "R106": "106",

    "R326": "326", "R325": "325", "R318": "318", "R314": "314",
    "R308": "308", "R303": "303",

    "R224": "224", "R220": "220",

    "R127": "127", "R123": "123", "R120": "120",
    "R119": "119", "R118": "118", "R117": "117", "R116": "116"
}

def build_svg_label_map(labels):
    num_to_label = {}
    for lk in labels:
        for num in re.findall(r'\d{3}', lk):
            num_to_label.setdefault(num, lk)
    canteen = next(
        (k for k in labels if any(w in k.lower()
         for w in ("столов", "canteen"))), None)
    result = {}
    for rect_id, token in SVG_RECT_TO_NUMBER.items():
        if token == "__canteen__":
            if canteen: result[rect_id] = canteen
        elif token in num_to_label:
            result[rect_id] = num_to_label[token]
    return result


# ══════════════════════════════════════════════════════════════════
#  APP
# ══════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Навигатор школы 2120", layout="wide")

for k, v in {
    "current_path":  None,
    "floor_control": 1,
    "_floor_seg":    1,
    "auth_mode":     "login",
    "user":          None,
    "sel_from":      None,
    "sel_to":        None,
}.items():
    st.session_state.setdefault(k, v)



# ── Авторизация ───────────────────────────────────────────────────

def _set_auth_background(image_path: str = "school_bg.jpg") -> None:
    import base64, pathlib
    p = pathlib.Path(image_path)
    b64 = ""
    if p.exists():
        b64 = base64.b64encode(p.read_bytes()).decode()
        ext = p.suffix.lstrip(".")
        bg_style = f"url('data:image/{ext};base64,{b64}')"
    else:
        # Запасной вариант, если картинка не найдется
        bg_style = "linear-gradient(135deg, #FFB100 0%, #FF8C00 100%)"

    st.markdown(f"""
<style>
/* Основной фон всей страницы */
[data-testid="stAppViewContainer"] {{
    background: {bg_style} center center / cover no-repeat fixed !important;
}}

/* Затемнение и размытие фона, чтобы текст читался */
[data-testid="stAppViewContainer"]::before {{
    content: "";
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35); /* Легкое затемнение */
    backdrop-filter: blur(4px);
    z-index: 0;
}}

/* Центрированный контейнер "Стеклянное окно" */
[data-testid="stVerticalBlock"] {{
    background: rgba(255, 255, 255, 0.15) !important; /* Полупрозрачный белый */
    backdrop-filter: blur(15px) !important; /* Сильное размытие внутри окна */
    -webkit-backdrop-filter: blur(15px);
    border: 1px solid rgba(255, 255, 255, 0.3); /* Тонкая светлая рамка */
    border-radius: 24px !important;
    padding: 24px 28px !important;
    max-width: 480px !important;
    margin: 0 auto; /* Отступ сверху и центровка */
    box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2) !important;
}}

/* Заголовок (цвет из фасада школы) */
h1 {{
    color: #ffffff !important; 
    text-align: center !important;
    font-weight: 800 !important;
    text-shadow: 2px 2px 10px rgba(0,0,0,0.5) !important;
    margin-bottom: 30px !important;
}}

/* Подзаголовки и метки полей */
h3, label, .stMarkdown p {{
    color: white !important;
    font-weight: 600 !important;
    text-shadow: 1px 1px 3px rgba(0,0,0,0.3);
}}

/* Стилизация полей ввода */
.stTextInput input {{
    background-color: rgba(255, 255, 255, 0.9) !important;
    border-radius: 12px !important;
    border: 2px solid transparent !important;
    transition: all 0.3s;
}}
.stTextInput input:focus {{
    border-color: #FFB100 !important;
    box-shadow: 0 0 10px rgba(255, 177, 0, 0.4) !important;
}}

/* Оранжевые кнопки как на здании */
.stButton button {{
    width: 100%;
    background-color: #FFB100 !important;
    color: white !important;
    font-weight: bold !important;
    border-radius: 12px !important;
    border: none !important;
    height: 45px !important;
    transition: transform 0.2s, background-color 0.2s !important;
}}

.stButton button:hover {{
    background-color: #FF8C00 !important;
    transform: scale(1.02);
    color: white !important;
}}

/* Убираем лишние отступы Streamlit сверху */
header {{ visibility: hidden; }}
[data-testid="stHeader"] {{ background: rgba(0,0,0,0); }}

</style>
""", unsafe_allow_html=True)


if st.session_state.user is None:
    _set_auth_background()
    st.title("Интерактивная карта школы №2120")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Войти"):       st.session_state.auth_mode = "login"
    with c2:
        if st.button("Регистрация"): st.session_state.auth_mode = "register"
    with c3:
        if st.button("Гость"):       st.session_state.auth_mode = "guest"

    mode = st.session_state.auth_mode

    if mode == "login":
        st.subheader("Вход")
        lg = st.text_input("Логин")
        pw = st.text_input("Пароль", type="password")
        if st.button("Войти", key="do_login"):
            row = login_user(lg, pw)
            if row:
                st.session_state.user = {"id": row[0], "role": row[1],
                                          "name": f"{row[2]} {row[3]}"}
                st.session_state.auth_mode = "logged"
                st.rerun()
            else:
                st.error("Неверный логин или пароль")

    elif mode == "register":
        st.subheader("Регистрация")
        lg = st.text_input("Придумайте логин", placeholder="Не менее 3 символов")
        pw = st.text_input("Пароль",  type="password", placeholder="Не менее 4 символов")
        fn = st.text_input("Имя",     max_chars=30)
        ln = st.text_input("Фамилия", max_chars=30)
        if st.button("Создать аккаунт"):
            if len(lg) < 3:   st.error("Логин слишком короткий")
            elif len(pw) < 4: st.error("Пароль слишком короткий")
            elif register_user(lg, pw, fn, ln):
                st.success("Аккаунт создан!")
                st.session_state.auth_mode = "login"
            else:
                st.error("Логин уже существует")

    elif mode == "guest":
        st.subheader("Режим гостя")
        u = st.text_input("Пожалуйста введите своё имя:")
        r = st.radio("Кем вы являетесь:", ["Родитель", "Гость школы", "Ученик"])
        if st.button(f"Войти как {r}"):
            st.session_state.user = {"id": None, "role": r, "name": u}
            st.session_state.auth_mode = "logged"
            st.rerun()

    st.stop()


# ── Данные ────────────────────────────────────────────────────────
G, POSITIONS, LABELS, CATEGORIES = build_graph()
DISPLAY_POINTS = sorted(LABELS.keys()) + sorted(CATEGORIES.keys())
SVG_LABEL_MAP  = build_svg_label_map(LABELS)


# ── QR-коды ──────────────────────────────────────────────────────
params = st.query_params
if "start" in params:
    qr_id = params["start"]
    if qr_id in POSITIONS and st.session_state.get("last_qr") != qr_id:
        inv = {v: k for k, v in LABELS.items()}
        lbl = inv.get(qr_id)
        if lbl:
            st.session_state.sel_from      = lbl
            st.session_state.current_path  = None
            st.session_state.floor_control = G.nodes[qr_id]["floor"]
            st.session_state._floor_needs_reset = True
            st.session_state.last_qr = qr_id
            st.toast(f"Локация: {lbl}")
    st.query_params.clear()
    st.rerun()


# ── Sidebar ───────────────────────────────────────────────────────
def _idx(val):
    try: return DISPLAY_POINTS.index(val) if val in DISPLAY_POINTS else None
    except ValueError: return None

with st.sidebar:
    st.title("Навигация")
    user = st.session_state.user
    st.caption(f"👤 {user['name']}  ·  {user['role']}")

    if st.button("Выйти", use_container_width=True):
        st.session_state.user      = None
        st.session_state.auth_mode = "login"
        components.html(
            "<script>localStorage.removeItem('nav2120_uid');</script>",
            height=0,
        )
        st.rerun()

    from_label = st.selectbox(
        "Ваше местоположение", DISPLAY_POINTS,
        index=_idx(st.session_state.sel_from),
        placeholder="Выберите кабинет или сканируйте QR",
    )
    if from_label != st.session_state.sel_from:
        st.session_state.sel_from     = from_label
        st.session_state.current_path = None
        nodes = resolve_selection(from_label or "", LABELS, CATEGORIES)
        if nodes:
            st.session_state.floor_control = G.nodes[nodes[0]]["floor"]
            st.session_state._floor_needs_reset = True

    to_label = st.selectbox(
        "Куда нужно попасть?", DISPLAY_POINTS,
        index=_idx(st.session_state.sel_to),
        placeholder="Начните вводить название...",
    )
    if to_label != st.session_state.sel_to:
        st.session_state.sel_to = to_label

    mgn_mode   = st.toggle("♿ Режим МГН", key="mgn_mode")
    show_icons = st.checkbox("Показать иконки", value=True)

    start_nodes = resolve_selection(st.session_state.sel_from or "", LABELS, CATEGORIES)
    end_nodes   = resolve_selection(st.session_state.sel_to   or "", LABELS, CATEGORIES)

    if st.button("Построить маршрут", use_container_width=True):
        path = find_best_path(G, start_nodes, end_nodes, mgn_mode)
        if path:
            st.session_state.current_path  = path
            st.session_state.floor_control = G.nodes[path[0]]["floor"]
            st.session_state._floor_needs_reset = True
            length = nx.path_weight(G, path, "weight")
            log_route(st.session_state.user["id"],
                      st.session_state.sel_from, st.session_state.sel_to, length)
            if st.session_state.sel_to:
                parts        = st.session_state.sel_to.split()
                teacher_name = " ".join(parts[-3:]) if len(parts) >= 3 else st.session_state.sel_to
                tid = get_teacher_telegram(teacher_name)
                if tid:
                    role = st.session_state.user.get("role")
                    name = st.session_state.user.get("name", "Гость")
                    if role and role != "Ученик":
                        mins = round((length // 3.5) / 72)
                        msg = (f"🔔 {role} {name} направляется к вам!\n"
                               f"Будет у вас через ~{mins} мин")
                        send_notifications_async(tid, msg, "danialgatalskij@gmail.com", msg)
                        
                else:
                    st.sidebar.warning("ℹ️ Telegram ID учителя не найден")
            st.rerun()
        else:
            st.error("Путь не найден")
        
    if st.button("🗑️ Сбросить маршрут", use_container_width=True):
        st.session_state.current_path = None
        st.session_state.sel_from     = None
        st.session_state.sel_to       = None
        st.session_state.floor_control = 1
        st.session_state._floor_seg = 1
        st.rerun()

# ── Основной контент ──────────────────────────────────────────────
st.title("Интерактивная карта школы 2120 Ш6")
st.markdown("### Выберите этаж для просмотра:")

# Сбрасываем виджет чтобы default всегда был актуальным
if st.session_state.get("_floor_needs_reset"):
    st.session_state._floor_seg = st.session_state.floor_control
    st.session_state._floor_needs_reset = False

floor_choice = st.segmented_control(
    "Этаж", options=[1, 2, 3], key="_floor_seg"
)
if floor_choice is not None and floor_choice != st.session_state.floor_control:
    st.session_state.floor_control = floor_choice


current_floor = st.session_state.floor_control

svg_file = SVG_TEMPLATE.format(floor=current_floor)
try:
    with open(svg_file, encoding="utf-8") as f:
        svg = f.read()
except FileNotFoundError:
    st.error(f"Файл {svg_file} не найден")
    st.stop()

svg = svg.replace("<svg", "<svg preserveAspectRatio='xMidYMid meet'", 1)

# ── Маршрут и маркеры ─────────────────────────────────────────────
route_svg = ""
path = st.session_state.current_path

cur_from = resolve_selection(st.session_state.sel_from or "", LABELS, CATEGORIES)
if cur_from:
    nid = cur_from[0]
    if G.nodes[nid]["floor"] == current_floor:
        cx, cy = POSITIONS[nid]
        route_svg += f"""<style>
@keyframes pulse{{0%{{r:5;opacity:.8}}50%{{r:10;opacity:.3}}100%{{r:5;opacity:.8}}}}
.you-are-here{{fill:#4B57FF;animation:pulse 2s infinite}}
</style>
<circle class="you-are-here" cx="{cx}" cy="{cy}" r="6"/>
<circle cx="{cx}" cy="{cy}" r="4" fill="#4B57FF" stroke="white" stroke-width="1"/>"""

cur_to = resolve_selection(st.session_state.sel_to or "", LABELS, CATEGORIES)
if cur_to:
    nid = cur_to[0]
    if G.nodes[nid]["floor"] == current_floor:
        cx, cy = POSITIONS[nid]
        route_svg += f"""<style>
@keyframes pulse3{{0%{{r:5;opacity:.85}}50%{{r:10;opacity:.35}}100%{{r:5;opacity:.85}}}}
.target-point{{fill:#FFA500;animation:pulse3 2s infinite}}
</style>
<circle class="target-point" cx="{cx}" cy="{cy}" r="6"/>
<circle cx="{cx}" cy="{cy}" r="4" fill="#FFA500" stroke="white" stroke-width="1"/>"""

if path:
    path_on_floor = [n for n in path if G.nodes[n]["floor"] == current_floor]
    if path_on_floor:
        pts     = " ".join(f"{POSITIONS[n][0]},{POSITIONS[n][1]}" for n in path_on_floor)
        is_last = path[-1] == path_on_floor[-1]
        ex, ey  = POSITIONS[path_on_floor[-1]]
        route_svg += f"""<style>
.route-line{{stroke:#ff4b4b;stroke-width:4;fill:none;stroke-linecap:round;
  stroke-linejoin:round;stroke-dasharray:6 8;animation:route-dash 1.2s linear infinite}}
@keyframes route-dash{{to{{stroke-dashoffset:-28}}}}
@keyframes pulse2{{0%{{r:5;opacity:.8}}50%{{r:10;opacity:.3}}100%{{r:5;opacity:.8}}}}
.end-point{{fill:#FFA500;animation:pulse2 2s infinite}}
</style>
<polyline class="route-line" points="{pts}"/>
<circle class="end-point" cx="{ex}" cy="{ey}" r="6"/>
<circle cx="{ex}" cy="{ey}" r="4"
  fill="{'#FF4B4B' if is_last else '#FFA500'}" stroke="white" stroke-width="1"/>"""

        for n in path_on_floor:
            if G.nodes[n].get("type", "").lower() in ("лестница", "лифт", "stair", "lift"):
                cx2, cy2 = POSITIONS[n]
                route_svg += (f'<circle cx="{cx2}" cy="{cy2}" r="4" '
                              f'fill="#FFA500" stroke="white" stroke-width="1"/>')

        length_m = nx.path_weight(G, path, "weight") // 3.5
        mins     = round(length_m / 72)
        st.sidebar.metric("Дистанция", f"{int(length_m)} м", f"{mins} мин. пешком")

        if is_last:
            st.success("Вы на нужном этаже")
        else:
            try:
                idx       = path.index(path_on_floor[-1])
                nxt       = path[idx + 1]
                nxt_floor = G.nodes[nxt]["floor"]
                t_type    = G.nodes[path_on_floor[-1]].get("type", "переход").lower()
                st.warning(f"Направьтесь к {t_type.capitalize()}. Далее: **{nxt_floor}-й этаж**.")
            except (IndexError, KeyError):
                st.info("Следуйте к переходу на другой этаж")

if route_svg:
    svg = svg.replace("</svg>", f"{route_svg}</svg>")


COMPONENT_HEIGHT = 720

click_result = _svg_map_component(
    svg        = svg,
    label_map  = json.dumps(SVG_LABEL_MAP, ensure_ascii=False),
    show_icons = show_icons,
    key        = "svg_map_click",
    default    = None,
    height     = COMPONENT_HEIGHT,
)

# ── Обработка клика ───────────────────────────────────────────────
if click_result is not None:
    # Защита от повторной обработки одного и того же клика
    if click_result != st.session_state.get("_last_click"):
        st.session_state._last_click = click_result
        action = click_result.get("action")
        label  = click_result.get("label", "")

        if action == "from" and (label in LABELS or label in CATEGORIES):
            st.session_state.sel_from     = label
            st.session_state.current_path = None
            nodes = resolve_selection(label, LABELS, CATEGORIES)
            if nodes:
                st.session_state.floor_control = G.nodes[nodes[0]]["floor"]
                st.session_state._floor_needs_reset = True
            st.rerun()

        elif action == "to" and (label in LABELS or label in CATEGORIES):
            st.session_state.sel_to = label
            st.rerun()

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

st.markdown("""
<style>
/* Контейнер popover — поднимаем выше за счет изменения bottom */
div[data-testid="stPopover"] {
    position: fixed !important;
    right: 24px !important;
    bottom: 100px !important; /* Увеличьте это значение, чтобы поднять кнопку выше */
    left: auto !important;
    width: auto !important;
    z-index: 9999;
}

/* Сама кнопка — меняем цвет на оранжевый */
div[data-testid="stPopover"] > button {
    width: 56px !important;
    height: 56px !important;
    border-radius: 50% !important;
    background: #FF8C00 !important; /* Насыщенный оранжевый */
    color: white !important;
    font-size: 22px !important;
    padding: 0 !important;
    border: none !important;
    /* Тень тоже лучше сделать теплой под цвет кнопки */
    box-shadow: 0 4px 20px rgba(255, 140, 0, 0.45) !important;
    transition: all 0.3s ease; /* Плавный переход для ховера */
}

/* Эффект при наведении — делаем оранжевый чуть темнее */
div[data-testid="stPopover"] > button:hover {
    background: #E67E00 !important; 
    transform: scale(1.08);
    box-shadow: 0 6px 25px rgba(255, 140, 0, 0.6) !important;
}
</style>
""", unsafe_allow_html=True)

with st.popover("❓"):
    st.subheader("Помощник ИИ")
    with st.container(height=280):
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    st.text_input("Ваш вопрос", key="llm_input", placeholder="Спроси что-нибудь...")
    send_msg = st.button("Отправить", key="llm_send", use_container_width=True)
    user_input = st.session_state.get("llm_input", "").strip()

    if send_msg and user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        known_rooms = sorted(LABELS.keys()) + sorted(CATEGORIES.keys())

        with st.chat_message("assistant"):
            result = st.write_stream(
                ask_llama_stream(st.session_state.chat_history, known_rooms, user["name"])
            )

        import re, json as _json

        def _extract_json_inline(text):
            m = re.search(r'\{[^{}]+\}', text, re.DOTALL)
            if not m:
                return None
            try:
                return _json.loads(m.group())
            except _json.JSONDecodeError:
                return None

        def _find_best_room_inline(query, rooms):
            if not query:
                return None
            if query in rooms:
                return query
            for num in re.findall(r'\d{3}', query or ""):
                for room in rooms:
                    if num in room:
                        return room
            q = (query or "").lower()
            for room in rooms:
                if q in room.lower() or room.lower() in q:
                    return room
            return None

        display_text = result
        cmd = _extract_json_inline(display_text)

        if cmd and cmd.get("action") == "navigate":
            resolved_to   = _find_best_room_inline(cmd.get("to"), known_rooms)
            resolved_from = _find_best_room_inline(cmd.get("from"), known_rooms)
            if resolved_to:
                st.session_state.sel_to = resolved_to
                if resolved_from:
                    st.session_state.sel_from = resolved_from

                mgn_mode = st.session_state.get("mgn_mode", False)
                start_nodes = resolve_selection(st.session_state.sel_from or "", LABELS, CATEGORIES)
                end_nodes = resolve_selection(resolved_to, LABELS, CATEGORIES)
                path = find_best_path(G, start_nodes, end_nodes, mgn_mode)

                if path:
                    st.session_state.current_path = path
                    st.session_state.floor_control = G.nodes[path[0]]["floor"]
                    st.session_state._floor_needs_reset = True
                    length = nx.path_weight(G, path, "weight")
                    log_route(st.session_state.user["id"],
                              st.session_state.sel_from, resolved_to, length)
                    mins = round((length // 3.5) / 72)
                    parts = ["✅ Маршрут построен"]
                    if resolved_from:
                        parts.append(f"от **{resolved_from}**")
                    parts.append(f"до **{resolved_to}**.")
                    parts.append(f"~{mins} мин. пешком.")
                    display_text = " ".join(parts)
                else:
                    st.session_state.current_path = None
                    display_text = f"Не удалось найти путь до **{resolved_to}**. Возможно, кабинет недоступен."
            else:
                display_text = f"Не нашёл кабинет «{cmd.get('to')}» в базе. Уточни название."

        st.session_state.chat_history.append({"role": "assistant", "content": display_text})
        st.session_state.llm_input = ""
        st.rerun()
