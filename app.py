import streamlit as st
import sqlite3
import networkx as nx
import streamlit.components.v1 as components
import hashlib
import requests



def send_telegram_message(chat_id, message):
    url = f"https://api.telegram.org/bot7237678765:AAFDdz906uHKoJYhSYG5SMNgH547OCZdw8g/sendMessage"
    params = {"chat_id": chat_id, "text": message}
    response = requests.get(url, params=params)
    return response.json()


DB_PATH = "school_map2120.db"

def get_teacher_telegram(person_name):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""SELECT telegram_id FROM teachers WHERE name = ? OR full_name = ?""", (person_name, person_name))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def login_user(login, password):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, role, first_name, last_name 
        FROM users 
        WHERE login=? AND password=?
    """, (login, hash_password(password)))

    row = cur.fetchone()
    conn.close()

    return row


def log_route(user_id, start, end, length):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO route_logs (user_id, from_point, to_point, length)
        VALUES (?, ?, ?, ?)
    """, (user_id, start, end, length))
    conn.commit()
    conn.close()


def register_user(login, password, first_name, last_name, role="Ученик"):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO users (login, password, first_name, last_name, role)
            VALUES (?, ?, ?, ?, ?)
        """, (
            login,
            hash_password(password),
            first_name,
            last_name,
            role
        ))

        conn.commit()
        conn.close()
        return True
    except:
        return False



SVG_TEMPLATE = "Floor{floor}_G.svg"

st.set_page_config(
    page_title="Навигатор школы 2120",
    layout="wide"
)

st.session_state.setdefault("current_path", None)
st.session_state.setdefault("floor_control", 1)
st.session_state.setdefault("qr_start", None)
st.session_state.setdefault("export_mode", False)
st.session_state.setdefault("auth_mode", "login")
st.session_state.setdefault("user", None)

if st.session_state.auth_mode != "logged":

    st.title("Навигатор школы 2120")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Войти"):
            st.session_state.auth_mode = "login"

    with col2:
        if st.button("Регистрация"):
            st.session_state.auth_mode = "register"

    with col3:
        if st.button("Гость"):
            st.session_state.auth_mode = "guest"


if st.session_state.user is None:

    if st.session_state.auth_mode == "login":
        st.subheader("Вход")

        login = st.text_input("Логин")
        password = st.text_input("Пароль", type="password")

        if st.button("Войти", key="login"):
            user = login_user(login, password)

            if user:
                st.session_state.user = {
                    "id": user[0],
                    "role": user[1],
                    "name": f"{user[2]} {user[3]}"
                }
                st.session_state.auth_mode = "logged"
                st.rerun()
            else:
                st.error("Неверный логин или пароль")

    elif st.session_state.auth_mode == "register":
        st.subheader("Регистрация")

        login = st.text_input("Придумайте логин", placeholder="Не менее 3 символов")
        password = st.text_input("Пароль", type="password", placeholder="Не менее 4 символов")
        first_name = st.text_input("Имя", max_chars=30)
        last_name = st.text_input("Фамилия", max_chars=30)

        if st.button("Создать аккаунт"):
            if len(login) < 3:
                st.error("Логин слишком короткий")
            elif len(password) < 4:
                st.error("Пароль слишком короткий")
            else:
                if register_user(login, password, first_name, last_name):
                    st.success("Аккаунт создан!")
                    st.session_state.auth_mode = "login"
                else:
                    st.error("Логин уже существует")
    
    elif st.session_state.auth_mode == "guest":
        st.subheader("Режим гостя")
        u = st.text_input("Пожалуйста введите своё имя:") 
        r = st.radio("Кем вы являетесь:",
                                     ["Родитель", "Гость школы", "Ученик"])
        
        
        if st.button(f"Войти как {r}"):
            st.session_state.user = {
                "id": None,
                "role": r,
                "name": u
            }
            st.session_state.auth_mode = "logged"
            st.rerun()


    st.stop()




def load_data_from_db(db_path: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, x, y, floor, type, label, person
        FROM nodes
    """)

    positions = {}
    floors = {}
    types = {}
    labels = {}
    categories = {}


    for node_id, x, y, floor, n_type, label, person in cur.fetchall():
        positions[node_id] = (x, y)
        floors[node_id] = floor
        types[node_id] = n_type or "regular"
        
        if label and person != None:
            labels[label + f" {person}"] = node_id

        else:
            labels[label] = node_id
        
        
        if n_type:
            categories.setdefault(n_type.capitalize(), []).append(node_id)

    cur.execute("SELECT node_from, node_to, weight FROM edges")
    edges = [(u, v, float(w)) for u, v, w in cur.fetchall()]

    conn.close()
    return positions, floors, types, labels, edges, categories


def resolve_selection(selection, labels, categories):
    if selection in labels:
        return [labels[selection]]
    if selection in categories:
        return categories[selection]
    return []

@st.cache_resource
def build_graph():
    POS, FLOORS, TYPES, LABELS, EDGES, CATEGORIES = load_data_from_db(DB_PATH)

    G = nx.Graph()
    for node_id, pos in POS.items():
        G.add_node(
            node_id,
            pos=pos,
            floor=FLOORS[node_id],
            type=TYPES[node_id]
        )

    G.add_weighted_edges_from(EDGES)

    return G, POS, LABELS, CATEGORIES


G, POSITIONS, LABELS, CATEGORIES = build_graph()
params = st.query_params

if st.session_state.qr_start:
    qr_node = st.session_state.qr_start

    inv_labels = {v: k for k, v in LABELS.items()}
    qr_label = inv_labels.get(qr_node)

    if qr_label:
        st.session_state.from_label = qr_label
        st.session_state.floor_control = G.nodes[qr_node]["floor"]

    st.session_state.qr_start = None


if "start" in params:
    qr_node_id = params["start"]
    
    if st.session_state.get("last_qr") != qr_node_id:
        if qr_node_id in POSITIONS:
            inv_labels = {v: k for k, v in LABELS.items()}
            qr_label = inv_labels.get(qr_node_id)
            st.session_state.qr_start = qr_node_id
            
            if qr_label:
                st.session_state["from_label"] = qr_label 
                st.session_state.floor_control = G.nodes[qr_node_id]["floor"]
                st.session_state["last_qr"] = qr_node_id
                st.toast(f"Локация: {qr_label}")
                st.rerun() 

def filter_graph_by_mobility(G, mgn):
    if mgn:
        forbidden = {"лестница", "staircase"}
    else:
        forbidden = {"лифт", "elevator"}

    allowed = [
        n for n, d in G.nodes(data=True)
        if str(d.get("type", "")).lower() not in forbidden
    ]
    return G.subgraph(allowed).copy()


def restrict_to_single_floor(G, floor):
    return G.subgraph([
        n for n, d in G.nodes(data=True)
        if d.get('floor') == floor
    ]).copy()


def find_best_path(G, starts, targets, mgn):
    best_path = None
    best_len = float("inf")

    base_G = filter_graph_by_mobility(G, mgn)

    for s in starts:
        for t in targets:
            if s not in base_G or t not in base_G:
                continue

            working_G = base_G

            if G.nodes[s]["floor"] == G.nodes[t]["floor"]:
                working_G = restrict_to_single_floor(
                    working_G,
                    G.nodes[s]["floor"]
                )

            try:
                path = nx.dijkstra_path(working_G, s, t, weight="weight")
                length = nx.path_weight(working_G, path, "weight")

                if length < best_len:
                    best_len = length
                    best_path = path

            except nx.NetworkXNoPath:
                pass

    return best_path


def sync_floor_with_start():
    label = st.session_state.get("from_label")
    if not label:
        return

    start_nodes = resolve_selection(label, LABELS, CATEGORIES)
    if not start_nodes:
        return

    node_id = start_nodes[0]
    st.session_state.floor_control = G.nodes[node_id]["floor"]
    st.session_state.current_path = None

with st.sidebar:
    st.title("Навигация")

    DISPLAY_POINTS = sorted(LABELS.keys())
    DISPLAY_POINTS += sorted(CATEGORIES.keys())
    from_label = st.selectbox(
        "Ваше местоположение",
        DISPLAY_POINTS,
        key="from_label",
        on_change=sync_floor_with_start,
        placeholder="Выберите кабинет или сканируйте QR"
    )

    to_label   = st.selectbox("Куда нужно попасть?", DISPLAY_POINTS, index=None, placeholder="Начните вводить название...")

    mgn_mode = st.toggle("♿ Режим МГН")
    show_icons = st.checkbox("Показать иконки", value=True)

    
    start_nodes = resolve_selection(from_label, LABELS, CATEGORIES)
    end_nodes   = resolve_selection(to_label, LABELS, CATEGORIES)

    if st.button("Построить маршрут", use_container_width=True):
        path = find_best_path(G, start_nodes, end_nodes, mgn_mode)
        teacher = " ".join(from_label.split()[-3:])
        
        if path:
            st.session_state.current_path = path
            start_node = path[0]
            start_floor = G.nodes[start_node]["floor"]
            st.session_state.floor_control = start_floor

            length = nx.path_weight(G, path, "weight")
            log_route(
            st.session_state.user["id"],
            from_label,
            to_label,
            length
            )
            
            if path and to_label:  
                teacher_name = " ".join(to_label.split()[-3:]) if len(to_label.split()) >= 3 else to_label
                
            telegram_id = get_teacher_telegram(teacher_name)
            if telegram_id:
                user_name = st.session_state.user.get("name", "Гость")
                user_role = st.session_state.user.get("role")
                                
                if user_role == None:
                    st.write("Вы не выбрали роль")

                length = nx.path_weight(G, path, "weight")
                time_min = round((length//3.5) / 72)
                
                if user_role != "Ученик":
                    message = f"🔔 {user_role} {user_name} направляется к вам!\nБудет у вас через ~{time_min} мин"
                
                    result = send_telegram_message(telegram_id, message)

                # if result.get("ok"):
                #     st.sidebar.success("✅ Уведомление отправлено учителю!")
                # else:
                #     st.sidebar.error("❌ Ошибка отправки уведомления")
            else:
                st.sidebar.warning("ℹ️ Telegram ID учителя не найден")

               
            st.rerun()
        else:
            st.error("Путь не найден")
    
    

st.title("Интерактивная карта школы 2120 Ш6")

st.markdown("### Выберите этаж для просмотра:")
st.segmented_control(
    "Этаж",
    options=[1, 2, 3],
    key="floor_control"
)

svg_file = SVG_TEMPLATE.format(floor=st.session_state.floor_control)

try:
    with open(svg_file, encoding="utf-8") as f:
        svg = f.read()
except FileNotFoundError:
    st.error(f"Файл {svg_file} не найден")
    st.stop()

icon_visibility = "visible" if show_icons else "hidden"

combined_styles = f"""
<style>
    iframe {{ border: none; }}
    svg {{
        width: 100%;
        height: 100%;
    }}
    
    #icons {{ 
        visibility: {icon_visibility} !important; 
        display: {'block' if show_icons else 'none'} !important;
    }}
    .route-line {{
        stroke: #ff4b4b;
        stroke-width: 4;
        fill: none;
        stroke-linecap: round;
        stroke-linejoin: round;
        stroke-dasharray: 6 8;
        animation: route-dash 1.2s linear infinite;
    }}

    @keyframes route-dash {{
        to {{ stroke-dashoffset: -28; }}
    }}

    @media print {{
    .stApp > header, [data-testid="stSidebar"], button {{ display: none !important; }}
    .main {{ padding: 0 !important; }}
    }}
</style>
"""

svg = svg.replace("<svg", "<svg preserveAspectRatio='xMidYMid meet'", 1)

path = st.session_state.current_path
route_svg_elements = "" 

current_start_node = resolve_selection(from_label, LABELS, CATEGORIES)
if current_start_node:
    node_id = current_start_node[0]
    if G.nodes[node_id]["floor"] == st.session_state.floor_control:
        start_coords = POSITIONS[node_id]

        route_svg_elements += f"""
        <style>
            @keyframes pulse {{
                0% {{ r: 5; opacity: 0.8; }}
                50% {{ r: 10; opacity: 0.3; }}
                100% {{ r: 5; opacity: 0.8; }}
            }}
            .you-are-here {{
                fill: #4B57FF;
                animation: pulse 2s infinite;
            }}

        </style>
        <circle class="you-are-here" cx="{start_coords[0]}" cy="{start_coords[1]}" r="6" />
        <circle cx="{start_coords[0]}" cy="{start_coords[1]}" r="4" fill={"#4B57FF"} stroke="white" stroke-width="1" />
        """

if path:
    path_on_floor = [
        n for n in path
        if G.nodes[n]["floor"] == st.session_state.floor_control
    ]

    if path_on_floor:
        coords = [POSITIONS[n] for n in path_on_floor]
        points = " ".join(f"{x},{y}" for x, y in coords)
        is_last_floor = path[-1] == path_on_floor[-1]

        route_svg_elements += f"""
        <polyline class="route-line" points="{points}" />
        <style>
            @keyframes pulse {{
                0% {{ r: 5; opacity: 0.8; }}
                50% {{ r: 10; opacity: 0.3; }}
                100% {{ r: 5; opacity: 0.8; }}
            }}
            .end-point {{
                fill: #FFA500;
                animation: pulse 2s infinite;
            }}     
        </style>
        <circle class="end-point" cx="{coords[-1][0]}" cy="{coords[-1][1]}" r="6" />
        <circle cx="{coords[-1][0]}" cy="{coords[-1][1]}" r="4"
                fill="{'#FF4B4B' if is_last_floor else '#FFA500'}" stroke="white" stroke-width="1" />
        """

        for node in path_on_floor:
            n_type = G.nodes[node].get('type', '').lower()
            if n_type in ['лестница', 'лифт', 'stair', 'lift']:
                c = POSITIONS[node]
                route_svg_elements += f'<circle cx="{c[0]}" cy="{c[1]}" r="4" fill="#FFA500" stroke="white" stroke-width="1" />'

        length = nx.path_weight(G, path, weight="weight")//3.5
        time_min = round(length / 72)
        st.sidebar.metric("Дистанция", f"{int(length)} м", f"{time_min} мин. пешком")
        if is_last_floor:
            st.success(f"Вы на нужном этаже")
        else:
            try:
                last_node_index = path.index(path_on_floor[-1])
                
                next_node = path[last_node_index + 1]
                
                next_floor = G.nodes[next_node]["floor"]
                
                transition_type = G.nodes[path_on_floor[-1]].get('type', 'переход').lower()
                
                st.warning(f"Направьтесь к {transition_type.capitalize()}. Далее: **{next_floor}-й этаж**.")
            except (IndexError, KeyError):
                st.info("Следуйте к переходу на другой этаж")

if route_svg_elements:
    svg = svg.replace("</svg>", f"{route_svg_elements}</svg>")

final_html = f"""
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>


{combined_styles}

<div style="margin-bottom: 10px;">
    <button onclick="downloadRoute()" id="btnSave" style="
        padding: 12px 24px; 
        background-color: #FF4B4B; 
        color: white; 
        border: none; 
        border-radius: 8px; 
        cursor: pointer;
        font-family: sans-serif;
    ">💾 Сохранить PNG</button>
</div>

<div id="capture" style="width:100%; height:70vh; border-radius:16px; overflow:hidden; border:1px solid #ddd; background:white;">
    {svg}
</div>

<script>
    async function downloadRoute() {{
        const btn = document.getElementById('btnSave');
        
        // ПРОВЕРКА: Загрузилась ли библиотека?
        if (typeof html2canvas === 'undefined') {{
            alert("Библиотека еще загружается. Подождите 2 секунды...");
            return;
        }}

        btn.innerText = "Обработка...";
        btn.disabled = true;

        try {{
            const element = document.getElementById('capture');
            
            // Настройка для корректного рендеринга SVG
            const canvas = await html2canvas(element, {{
                scale: 2,
                useCORS: true,
                allowTaint: true,
                backgroundColor: "#ffffff",
                logging: false
            }});

            const link = document.createElement('a');
            link.download = 'marshrute_2120.png';
            link.href = canvas.toDataURL('image/png');
            link.click();
            
            btn.innerText = "✅ Готово";
        }} catch (err) {{
            console.error(err);
            alert("Ошибка: " + err.message);
            btn.innerText = "❌ Ошибка";
        }} finally {{
            setTimeout(() => {{
                btn.innerText = "💾 Сохранить PNG";
                btn.disabled = false;
            }}, 2000);
        }}
    }}
</script>
"""


components.html(final_html, height=800, scrolling=False)

