"""
Vast.ai GPU Market Monitoring Web Application.
Built with Streamlit and Plotly for tracking GPU pricing, percentiles (P10, Median, P90),
and availability/utilization metrics in real time.
"""

import os
import sys
import hashlib

import datetime
import io
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from typing import Optional, List, Dict, Any, Union, Tuple

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

from vast_client import (
    VastAIClient,
    VastAPIError,
    VastAuthError,
    VastRateLimitError,
    VastConnectionError,
    GPU_PRESETS,
    GPU_DEFAULT_SPECS,
    get_gpu_specs,
    calculate_roi_table,
    calculate_roi_table_by_config,
    RIG_PLATFORM_SPECS,
    get_platform_specs,
    load_preferences,
    save_preferences,
    get_env_or_secret_api_key,
    get_kyiv_now,
    init_history_db,
    KYIV_TZ,
)

# Ensure database schema is initialized on start
try:
    init_history_db()
except Exception:
    pass


# Page Configuration
st.set_page_config(
    page_title="Vast.ai GPU Price & Utilization Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #38BDF8 0%, #818CF8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #94A3B8;
        font-size: 1rem;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: #1E293B;
        border-radius: 12px;
        padding: 16px;
        border: 1px solid #334155;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def format_time_ago(ts: Union[datetime.datetime, str, None]) -> str:
    """Formats timestamp into Ukrainian relative time 'X хв тому' in Kyiv timezone."""
    if ts is None or not str(ts).strip():
        return "ще немає"
    if isinstance(ts, str):
        try:
            ts = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                ts = datetime.datetime.fromisoformat(ts)
            except Exception:
                return str(ts)

    if isinstance(ts, datetime.datetime) and ts.tzinfo is not None:
        try:
            ts = ts.astimezone(KYIV_TZ).replace(tzinfo=None)
        except Exception:
            ts = ts.replace(tzinfo=None)

    now = get_kyiv_now()
    delta = now - ts
    total_seconds = int(delta.total_seconds())

    if total_seconds < 0:
        return "щойно"
    if total_seconds < 60:
        return f"щойно ({total_seconds} с тому)"

    minutes = total_seconds // 60
    if minutes == 1:
        return "1 хв тому"
    elif 2 <= minutes % 10 <= 4 and (minutes % 100 < 10 or minutes % 100 >= 20):
        return f"{minutes} хв тому"
    elif minutes < 60:
        return f"{minutes} хв тому"

    hours = minutes // 60
    if hours == 1:
        return "1 год тому"
    elif 2 <= hours % 10 <= 4 and (hours % 100 < 10 or hours % 100 >= 20):
        return f"{hours} год тому"
    elif hours < 24:
        return f"{hours} год тому"

    days = hours // 24
    return f"{days} дн тому"

def get_default_api_key() -> str:
    """Retrieves API key from st.secrets, environment, or secrets.toml without hardcoded values."""
    return get_env_or_secret_api_key()


def mask_api_key(key: str) -> str:
    """Returns masked representation of an API key for secure UI display."""
    if not key or len(key) < 14:
        return "••••••••••••••••"
    return f"{key[:8]}••••••••••••{key[-6:]}"



def generate_session_token(password: str) -> str:
    """Generates a secure deterministic session hash for URL persistence."""
    return hashlib.sha256((password + "_vast_session_salt_2026").encode("utf-8")).hexdigest()[:24]


def check_password() -> bool:
    """Returns True if the user is authenticated, else displays a password login form."""
    configured_password = ""
    try:
        configured_password = str(st.secrets.get("APP_PASSWORD", ""))
    except Exception:
        configured_password = ""

    if not configured_password:
        configured_password = "vast_password_2026"

    expected_token = generate_session_token(configured_password)

    # 1. Check if authenticated in current session state
    if st.session_state.get("authenticated", False):
        return True

    # 2. Check persistent session via query params (URL token)
    try:
        if st.query_params.get("auth") == expected_token:
            st.session_state["authenticated"] = True
            return True
    except Exception:
        pass

    def password_entered():
        entered_pass = st.session_state.get("password_input", "")
        remember_me = st.session_state.get("remember_me_input", True)
        if entered_pass == configured_password:
            st.session_state["authenticated"] = True
            st.session_state.pop("password_input", None)
            st.session_state.pop("auth_error", None)
            if remember_me:
                try:
                    st.query_params["auth"] = expected_token
                except Exception:
                    pass
        else:
            st.session_state["authenticated"] = False
            st.session_state["auth_error"] = True

    # Render Clean Login Screen
    st.markdown(
        """
        <div style="max-width: 440px; margin: 40px auto 20px auto; padding: 24px; background: #1E293B; border-radius: 16px; border: 1px solid #334155; text-align: center;">
            <div style="font-size: 2.8rem; margin-bottom: 8px;">⚡</div>
            <h2 style="color: #F8FAFC; margin-bottom: 6px; font-weight: 700;">Vast.ai Monitor</h2>
            <p style="color: #94A3B8; font-size: 0.95rem; margin-bottom: 0;">Доступ обмежено. Введіть пароль для входу:</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_l1, col_l2, col_l3 = st.columns([1, 1.2, 1])
    with col_l2:
        with st.form("login_form"):
            st.text_input(
                "Пароль:",
                type="password",
                key="password_input",
                placeholder="Введіть пароль доступу...",
            )
            st.checkbox("Запам'ятати мене (зберегти сесію)", value=True, key="remember_me_input")
            submit_login = st.form_submit_button("🔐 Увійти в систему", use_container_width=True, on_click=password_entered)

        if st.session_state.get("auth_error", False):
            st.error("❌ Невірний пароль! Спробуйте ще раз.")

        st.caption("🔒 Сесія захищена та зберігається на цьому пристрої.")

    return False


if not check_password():
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def load_vast_data(api_key: str, selected_gpus_tuple: tuple) -> pd.DataFrame:
    """Fetches and caches active offers from Vast.ai API for 5 minutes and saves snapshot to SQLite."""
    client = VastAIClient(api_key=api_key)
    selected_gpus_list = list(selected_gpus_tuple) if selected_gpus_tuple else None
    df = client.fetch_all_selected_offers(selected_gpus=selected_gpus_list)
    if not df.empty:
        try:
            VastAIClient.record_raw_offers_snapshot(df)
            summary_df_gpu = VastAIClient.calculate_summary_stats(df, price_mode="per_gpu")
            VastAIClient.record_real_snapshot(summary_df_gpu, price_mode="per_gpu")
            summary_df_inst = VastAIClient.calculate_summary_stats(df, price_mode="per_instance")
            VastAIClient.record_real_snapshot(summary_df_inst, price_mode="per_instance")
        except Exception as e:
            pass
    else:
        # Fallback to local SQLite database if live fetch yielded empty (e.g. network glitch)
        try:
            import sqlite3
            if os.path.exists(DB_PATH):
                conn = sqlite3.connect(DB_PATH)
                fallback_df = pd.read_sql_query(
                    """
                    SELECT bundle_id, machine_id, raw_gpu_name, display_name, gpu_ram_gb,
                           num_gpus, dph_total, dph_per_gpu, dph_base, rentable, rented, is_bid,
                           reliability_pct, dlperf, inet_down_mbps, inet_up_mbps, geolocation
                    FROM raw_offers_history
                    WHERE snapshot_time = (SELECT MAX(snapshot_time) FROM raw_offers_history)
                    """,
                    conn,
                )
                conn.close()
                if not fallback_df.empty:
                    df = fallback_df
        except Exception:
            pass
    return df


def create_price_line_chart(timeline_df: pd.DataFrame, price_label: str, hist_summary_df: Optional[pd.DataFrame] = None) -> go.Figure:
    """Creates an interactive Plotly line chart displaying Median, Mean, P10, and P90 trends."""
    fig = go.Figure()

    if timeline_df.empty:
        return fig

    gpus = timeline_df["gpu_name"].unique()
    colors = px.colors.qualitative.Plotly + px.colors.qualitative.Bold

    for idx, gpu in enumerate(gpus):
        gpu_data = timeline_df[timeline_df["gpu_name"] == gpu].sort_values("timestamp")
        color = colors[idx % len(colors)]
        avg_median = gpu_data["median_price"].mean()

        # Median Price Line (Solid)
        fig.add_trace(
            go.Scatter(
                x=gpu_data["timestamp"],
                y=gpu_data["median_price"],
                mode="lines+markers",
                name=f"{gpu} (Медіана, сер: ${avg_median:.4f})",
                line=dict(color=color, width=3),
                marker=dict(size=5),
                hovertemplate=f"<b>{gpu} (Медіана)</b><br>Час: %{{x|%Y-%m-%d %H:%M}}<br>Ціна: $%{{y:.4f}}/год (Сер: ${avg_median:.4f})<extra></extra>",
            )
        )

        # Mean Price Line (Dash-dot)
        if "mean_price" in gpu_data.columns:
            avg_mean = gpu_data["mean_price"].mean()
            fig.add_trace(
                go.Scatter(
                    x=gpu_data["timestamp"],
                    y=gpu_data["mean_price"],
                    mode="lines",
                    name=f"{gpu} (Сер. ціна, сер: ${avg_mean:.4f})",
                    line=dict(color=color, width=1.8, dash="dashdot"),
                    hovertemplate=f"<b>{gpu} (Сер. ціна)</b><br>Час: %{{x|%Y-%m-%d %H:%M}}<br>Ціна: $%{{y:.4f}}/год<extra></extra>",
                )
            )

        # P90 Price Line (Dashed, upper bound)
        fig.add_trace(
            go.Scatter(
                x=gpu_data["timestamp"],
                y=gpu_data["p90_price"],
                mode="lines",
                name=f"{gpu} (P90)",
                line=dict(color=color, width=1.5, dash="dash"),
                hovertemplate=f"<b>{gpu} (P90)</b>: $%{{y:.4f}}/год<extra></extra>",
            )
        )

        # P10 Price Line (Dotted, lower bound)
        fig.add_trace(
            go.Scatter(
                x=gpu_data["timestamp"],
                y=gpu_data["p10_price"],
                mode="lines",
                name=f"{gpu} (P10)",
                line=dict(color=color, width=1.5, dash="dot"),
                hovertemplate=f"<b>{gpu} (P10)</b>: $%{{y:.4f}}/год<extra></extra>",
            )
        )

    fig.update_layout(
        title=dict(text=f"<b>Динаміка цін GPU ({price_label})</b>", font=dict(size=18)),
        xaxis=dict(title="Період", showgrid=True, gridcolor="#334155"),
        yaxis=dict(title=f"Ціна ({price_label})", showgrid=True, gridcolor="#334155", tickprefix="$"),
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
    )
    return fig



def create_price_box_chart(df: pd.DataFrame, price_col: str, price_label: str) -> go.Figure:
    """Creates a box plot showing the price distribution per GPU model."""
    fig = px.box(
        df,
        x="display_name",
        y=price_col,
        color="display_name",
        points="all",
        title=f"<b>Розподіл цін за моделями GPU ({price_label})</b>",
        labels={"display_name": "Модель GPU", price_col: f"Ціна ({price_label})"},
        template="plotly_dark",
    )
    fig.update_layout(
        showlegend=False,
        yaxis=dict(tickprefix="$", showgrid=True, gridcolor="#334155"),
        xaxis=dict(showgrid=False),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


def create_utilization_chart(live_df: pd.DataFrame, hist_df: Optional[pd.DataFrame] = None, days_back: int = 7) -> go.Figure:
    """Creates a comparative horizontal bar chart displaying Live Utilization vs Historical Average Utilization %."""
    if live_df.empty:
        return go.Figure()

    merged_df = live_df[["Карта", "Утилізація (%)", "Доступно (шт)", "Всього серверів (шт)"]].copy()
    merged_df = merged_df.rename(columns={"Утилізація (%)": "Live Утилізація (%)"})

    if hist_df is not None and not hist_df.empty and "Утилізація (%)" in hist_df.columns:
        hist_map = dict(zip(hist_df["Карта"], hist_df["Утилізація (%)"]))
        merged_df["Сер. утилізація (%)"] = merged_df["Карта"].map(hist_map).fillna(merged_df["Live Утилізація (%)"])
    else:
        merged_df["Сер. утилізація (%)"] = merged_df["Live Утилізація (%)"]

    sorted_df = merged_df.sort_values(by="Сер. утилізація (%)", ascending=True)

    fig = go.Figure()

    # Trace 1: Historical Average Utilization over period
    fig.add_trace(
        go.Bar(
            y=sorted_df["Карта"],
            x=sorted_df["Сер. утилізація (%)"],
            orientation="h",
            name=f"Сер. за {days_back} дн. (%)",
            marker=dict(color="#38bdf8"),
            text=[f"{v:.1f}% (сер.)" for v in sorted_df["Сер. утилізація (%)"]],
            textposition="auto",
            hovertemplate="<b>%{y}</b><br>Сер. утилізація за період: %{x:.1f}%<extra></extra>",
        )
    )

    # Trace 2: Live Current Utilization
    fig.add_trace(
        go.Bar(
            y=sorted_df["Карта"],
            x=sorted_df["Live Утилізація (%)"],
            orientation="h",
            name="Поточна Live (%)",
            marker=dict(color="#818cf8"),
            text=[f"{v:.1f}%" for v in sorted_df["Live Утилізація (%)"]],
            textposition="auto",
            hovertemplate="<b>%{y}</b><br>Поточна Live утилізація: %{x:.1f}%<extra></extra>",
        )
    )

    fig.update_layout(
        title=dict(text=f"<b>Рівень утилізації GPU: Поточний (Live) vs Сер. за {days_back} дн.</b>", font=dict(size=18)),
        barmode="group",
        xaxis=dict(title="Утилізація (%)", range=[0, 105], showgrid=True, gridcolor="#334155"),
        yaxis=dict(title="Модель GPU", showgrid=False),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


def create_utilization_timeline_chart(timeline_df: pd.DataFrame, hist_df: Optional[pd.DataFrame] = None) -> go.Figure:
    """Creates a time series line chart showing GPU utilization % over time with mean reference values."""
    if timeline_df.empty:
        return go.Figure()

    fig = go.Figure()
    gpus = timeline_df["gpu_name"].unique()
    colors = px.colors.qualitative.Plotly + px.colors.qualitative.Bold

    for i, gpu in enumerate(gpus):
        gpu_data = timeline_df[timeline_df["gpu_name"] == gpu].sort_values("timestamp")
        color = colors[i % len(colors)]
        avg_u = gpu_data["utilization_pct"].mean()

        fig.add_trace(
            go.Scatter(
                x=gpu_data["timestamp"],
                y=gpu_data["utilization_pct"],
                mode="lines+markers",
                name=f"{gpu} (Сер: {avg_u:.1f}%)",
                line=dict(color=color, width=2.5),
                marker=dict(size=4),
                hovertemplate=f"<b>{gpu}</b><br>Час: %{{x|%Y-%m-%d %H:%M}}<br>Утилізація: %{{y:.1f}}% (Сер: {avg_u:.1f}%)<extra></extra>",
            )
        )

    fig.update_layout(
        title=dict(text="<b>Історична динаміка утилізації GPU (%) у часі</b>", font=dict(size=18)),
        xaxis=dict(title="Період", showgrid=True, gridcolor="#334155"),
        yaxis=dict(title="Утилізація (%)", range=[0, 105], showgrid=True, gridcolor="#334155"),
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
    )
    return fig



def create_roi_financials_chart(roi_df: pd.DataFrame) -> go.Figure:
    """Creates a grouped bar chart comparing Gross Revenue, Electricity Cost, and Net Profit."""
    if roi_df.empty:
        return go.Figure()

    sorted_df = roi_df.sort_values(by="Чистий прибуток ($/міс)", ascending=False)
    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            name="Валовий дохід ($/міс)",
            x=sorted_df["Карта"],
            y=sorted_df["Валовий дохід ($/міс)"],
            marker_color="#38bdf8",
            hovertemplate="<b>%{x}</b><br>Валовий дохід: $%{y:.2f}/міс<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Витрати на світло ($/міс)",
            x=sorted_df["Карта"],
            y=sorted_df["Світло ($/міс)"],
            marker_color="#f87171",
            hovertemplate="<b>%{x}</b><br>Світло: $%{y:.2f}/міс<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Чистий прибуток ($/міс)",
            x=sorted_df["Карта"],
            y=sorted_df["Чистий прибуток ($/міс)"],
            marker_color="#4ade80",
            hovertemplate="<b>%{x}</b><br>Чистий прибуток: $%{y:.2f}/міс<extra></extra>",
        )
    )

    fig.update_layout(
        title=dict(text="<b>Фінансовий баланс на місяць: Дохід vs Світло vs Прибуток</b>", font=dict(size=17)),
        barmode="group",
        xaxis=dict(title="Модель GPU", showgrid=False),
        yaxis=dict(title="USD ($ / місяць)", showgrid=True, gridcolor="#334155", tickprefix="$"),
        template="plotly_dark",
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
    )
    return fig


def create_roi_payback_chart(roi_df: pd.DataFrame) -> go.Figure:
    """Creates a horizontal bar chart showing payback period in months and annual ROI."""
    if roi_df.empty:
        return go.Figure()

    valid_df = roi_df[pd.notnull(roi_df["Окупність (місяців)"])].copy()
    if valid_df.empty:
        return go.Figure()

    valid_df["Окупність_num"] = pd.to_numeric(valid_df["Окупність (місяців)"], errors="coerce")
    valid_df = valid_df.dropna(subset=["Окупність_num"]).sort_values(by="Окупність_num", ascending=True)
    if valid_df.empty:
        return go.Figure()

    fig = px.bar(
        valid_df,
        x="Окупність_num",
        y="Карта",
        orientation="h",
        color="Річний ROI (%)",
        color_continuous_scale="Viridis",
        title="<b>Термін окупності обладнання (місяців) та Річний ROI (%)</b>",
        labels={"Окупність_num": "Окупність (місяців)", "Карта": "Модель GPU"},
        template="plotly_dark",
        text=valid_df.apply(lambda r: f"{r['Окупність_num']:.1f} міс. (ROI {r['Річний ROI (%)']}%)", axis=1),
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        xaxis=dict(showgrid=True, gridcolor="#334155"),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig

def create_config_utilization_chart(config_df: pd.DataFrame) -> go.Figure:
    """Creates a grouped bar chart displaying utilization % by GPU model and number of cards (1x, 2x, 4x, 8x)."""
    if config_df.empty:
        return go.Figure()

    display_df = config_df[config_df["К-сть GPU"].isin([1, 2, 4, 8])].copy()
    if display_df.empty:
        display_df = config_df.copy()

    display_df["Конфіг_лейбл"] = display_df["К-сть GPU"].apply(lambda x: f"{x}x GPU")

    fig = px.bar(
        display_df,
        x="Карта",
        y="Утилізація (%)",
        color="Конфіг_лейбл",
        barmode="group",
        title="<b>Утилізація GPU (%) в розрізі конфігурацій (1x / 2x / 4x / 8x карт)</b>",
        labels={"Карта": "Модель GPU", "Утилізація (%)": "Утилізація (%)", "Конфіг_лейбл": "Конфігурація"},
        template="plotly_dark",
        text=display_df["Утилізація (%)"].apply(lambda v: f"{v:.1f}%"),
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        yaxis=dict(range=[0, 115], showgrid=True, gridcolor="#334155"),
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def create_config_roi_profit_chart(config_roi_df: pd.DataFrame) -> go.Figure:
    """Creates a bar chart comparing Monthly Net Profit across multi-GPU server configurations."""
    if config_roi_df.empty:
        return go.Figure()

    display_df = config_roi_df[config_roi_df["К-сть GPU"].isin([1, 2, 4, 8])].copy()
    if display_df.empty:
        display_df = config_roi_df.copy()

    display_df = display_df.sort_values(by="Чистий прибуток ($/міс)", ascending=False)

    fig = px.bar(
        display_df,
        x="Конфігурація",
        y="Чистий прибуток ($/міс)",
        color="Річний ROI (%)",
        color_continuous_scale="Viridis",
        title="<b>Чистий прибуток сервера ($/місяць) та Річний ROI (%) в розрізі конфігурацій</b>",
        labels={"Конфігурація": "Конфігурація сервера", "Чистий прибуток ($/міс)": "Чистий прибуток ($/міс)"},
        template="plotly_dark",
        text=display_df.apply(lambda r: f"+${r['Чистий прибуток ($/міс)']:.0f}/міс (ROI {r['Річний ROI (%)']}%)", axis=1),
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        yaxis=dict(showgrid=True, gridcolor="#334155", tickprefix="$"),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


def create_machine_price_timeline_chart(timeline_df: pd.DataFrame, machine_id: int, gpu_name: str) -> go.Figure:
    """Creates an interactive Plotly chart showing price history and rental states for a specific machine."""
    if timeline_df.empty:
        return go.Figure()

    df = timeline_df.copy()
    df["snapshot_time"] = pd.to_datetime(df["snapshot_time"])
    df = df.sort_values(by="snapshot_time", ascending=True)

    fig = go.Figure()

    # Base line connecting all price points
    fig.add_trace(go.Scatter(
        x=df["snapshot_time"],
        y=df["dph_total"],
        mode="lines",
        line=dict(color="#64748B", width=2, dash="dot"),
        name="Динаміка ставки ($/год)",
        hoverinfo="skip",
    ))

    # Split into Rented (Green) and Available (Yellow) scatter markers
    rented_mask = df["rentable"] == 0
    rented_points = df[rented_mask]
    available_points = df[~rented_mask]

    if not rented_points.empty:
        fig.add_trace(go.Scatter(
            x=rented_points["snapshot_time"],
            y=rented_points["dph_total"],
            mode="markers",
            marker=dict(color="#10B981", size=9, symbol="circle", line=dict(color="#064E3B", width=1)),
            name="🟢 В оренді (Зайнята)",
            customdata=np.stack((
                rented_points["dph_per_gpu"],
                rented_points["num_gpus"],
                rented_points["reliability_pct"],
                rented_points["dlperf"]
            ), axis=-1),
            hovertemplate="<b>🟢 В оренді</b><br>Час: %{x|%Y-%m-%d %H:%M}<br>Ціна машини: $%{y:.4f}/год<br>Ціна / 1 GPU: $%{customdata[0]:.4f}/год<br>GPU: %{customdata[1]}x<br>Надійність: %{customdata[2]:.1f}%<br>DLPerf: %{customdata[3]:.1f}<extra></extra>",
        ))

    if not available_points.empty:
        fig.add_trace(go.Scatter(
            x=available_points["snapshot_time"],
            y=available_points["dph_total"],
            mode="markers",
            marker=dict(color="#F59E0B", size=9, symbol="diamond", line=dict(color="#78350F", width=1)),
            name="🟡 Вільна (Очікує клієнта)",
            customdata=np.stack((
                available_points["dph_per_gpu"],
                available_points["num_gpus"],
                available_points["reliability_pct"],
                available_points["dlperf"]
            ), axis=-1),
            hovertemplate="<b>🟡 Вільна</b><br>Час: %{x|%Y-%m-%d %H:%M}<br>Ціна машини: $%{y:.4f}/год<br>Ціна / 1 GPU: $%{customdata[0]:.4f}/год<br>GPU: %{customdata[1]}x<br>Надійність: %{customdata[2]:.1f}%<br>DLPerf: %{customdata[3]:.1f}<extra></extra>",
        ))

    fig.update_layout(
        title=f"<b>Історія ставки оренди ($/год) та статусів Machine #{machine_id} ({gpu_name})</b>",
        xaxis=dict(title="Час зрізу (Київський час)", showgrid=True, gridcolor="#334155"),
        yaxis=dict(title="Ціна сервера ($/год)", showgrid=True, gridcolor="#334155", tickprefix="$"),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


def create_machine_occupancy_timeline_chart(timeline_df: pd.DataFrame, machine_id: int) -> go.Figure:
    """Creates a chronological status distribution chart for machine occupancy."""
    if timeline_df.empty:
        return go.Figure()

    df = timeline_df.copy()
    df["snapshot_time"] = pd.to_datetime(df["snapshot_time"])
    df = df.sort_values(by="snapshot_time", ascending=True)

    df["state_text"] = df["rentable"].apply(lambda r: "🟢 В оренді" if r == 0 else "🟡 Вільна")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["snapshot_time"],
        y=[1] * len(df),
        marker=dict(
            color=df["rentable"].apply(lambda r: "#10B981" if r == 0 else "#F59E0B")
        ),
        customdata=df["state_text"],
        hovertemplate="Час: %{x|%Y-%m-%d %H:%M}<br>Статус: %{customdata}<extra></extra>",
        showlegend=False,
    ))

    fig.update_layout(
        title="<b>Хронологічна стрічка заповнення машини (Зелений = Зайнята, Жовтий = Доступна)</b>",
        xaxis=dict(title="Час", showgrid=False),
        yaxis=dict(showticklabels=False, showgrid=False, range=[0, 1.2]),
        height=180,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        margin=dict(l=40, r=40, t=50, b=30),
    )
    return fig


def render_column_order_selector(table_key: str, available_columns: List[str], label: str = "⚙️ Налаштувати положення та видимість колонок") -> List[str]:
    """Renders a multiselect control for custom column ordering/visibility with persistent state."""
    if "saved_column_orders" not in st.session_state:
        st.session_state["saved_column_orders"] = {}

    saved_map = st.session_state["saved_column_orders"]
    if table_key in saved_map and saved_map[table_key]:
        saved = [c for c in saved_map[table_key] if c in available_columns]
        missing = [c for c in available_columns if c not in saved]
        current_default = saved + missing
    else:
        current_default = available_columns

    with st.expander(label, expanded=False):
        col_ord_sel, col_reset_btn = st.columns([4, 1])
        with col_ord_sel:
            selected_order = st.multiselect(
                "Порядок та видимість колонок (перетягуйте елементи для зміни черговості):",
                options=available_columns,
                default=current_default,
                key=f"col_order_widget_{table_key}",
                help="Оберіть потрібні колонки та вкажіть порядок їх відображення.",
            )
        with col_reset_btn:
            if st.button("🔄 Скинути порядок", key=f"reset_cols_{table_key}", help="Скинути положення колонок до стандарту"):
                st.session_state["saved_column_orders"][table_key] = list(available_columns)
                save_preferences({"saved_column_orders": st.session_state["saved_column_orders"]})
                st.rerun()

        if selected_order and selected_order != current_default:
            st.session_state["saved_column_orders"][table_key] = selected_order
            save_preferences({"saved_column_orders": st.session_state["saved_column_orders"]})

    return selected_order if selected_order else current_default


# --- SIDEBAR CONTROLS ---
with st.sidebar:
    st.markdown("### ⚙️ Налаштування моніторингу")

    # Load saved user preferences
    saved_prefs = load_preferences()

    if "custom_gpu_prices" not in st.session_state:
        st.session_state["custom_gpu_prices"] = saved_prefs.get("custom_gpu_prices", {})
    if "custom_load_w" not in st.session_state:
        st.session_state["custom_load_w"] = saved_prefs.get("custom_load_w", {})
    if "custom_idle_w" not in st.session_state:
        st.session_state["custom_idle_w"] = saved_prefs.get("custom_idle_w", {})
    if "calc_currency" not in st.session_state:
        st.session_state["calc_currency"] = saved_prefs.get("calc_currency", "USD ($)")
    if "usd_uah_rate" not in st.session_state:
        st.session_state["usd_uah_rate"] = float(saved_prefs.get("usd_uah_rate", 41.5))
    if "usd_cny_rate" not in st.session_state:
        st.session_state["usd_cny_rate"] = float(saved_prefs.get("usd_cny_rate", 7.25))

    if "saved_column_orders" not in st.session_state:
        st.session_state["saved_column_orders"] = saved_prefs.get("saved_column_orders", {})
    if "watched_machine_ids" not in st.session_state:
        st.session_state["watched_machine_ids"] = saved_prefs.get("watched_machine_ids", [55957, 29796])
    if "watched_host_ids" not in st.session_state:
        st.session_state["watched_host_ids"] = saved_prefs.get("watched_host_ids", [69666])



    # Secure API Key Handling
    configured_api_key = get_default_api_key()
    if "session_custom_api_key" not in st.session_state:
        st.session_state["session_custom_api_key"] = configured_api_key

    if configured_api_key:
        st.markdown(f"🔑 **Vast.ai API Key:** `{mask_api_key(st.session_state['session_custom_api_key'])}`")
        st.caption("🔒 *Завантажено захищено із Secrets / Env*")
        with st.expander("✏️ Змінити API ключ для сесії", expanded=False):
            override_key = st.text_input(
                "Введіть інший ключ:",
                value="",
                type="password",
                placeholder="Вставте новий ключ...",
                help="Залиште пустим для використання базового ключа із Secrets",
            )
            if override_key.strip() and override_key.strip() != st.session_state["session_custom_api_key"]:
                st.session_state["session_custom_api_key"] = override_key.strip()
                st.rerun()
            if st.button("🔄 Скинути ключ до Secrets"):
                st.session_state["session_custom_api_key"] = configured_api_key
                st.rerun()

        api_key_input = st.session_state["session_custom_api_key"]
    else:
        api_key_input = st.text_input(
            "🔑 Vast.ai API Key:",
            type="password",
            placeholder="Введіть ваш API ключ Vast.ai...",
            help="API ключ для доступу до сервісу Vast.ai",
        )



    auto_refresh = st.checkbox("⏱ Автооновлення кожні 5 хв", value=saved_prefs.get("auto_refresh", True))
    if auto_refresh and st_autorefresh:
        st_autorefresh(interval=300000, key="gpu_refresh_timer_5min")

    if st.button("🔄 Оновити дані", use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_market_fetch_ts"] = get_kyiv_now()
        st.rerun()

    st.markdown("---")

    # GPU Model Selection with Persistence and Quick Presets
    st.markdown("#### 🎮 Вибір GPU карт")

    if "selected_gpus_key" not in st.session_state:
        initial_gpus = [g for g in saved_prefs.get("selected_gpus", []) if g in GPU_PRESETS] or ["RTX 4090", "RTX 3090", "Tesla V100 16GB", "Tesla V100 32GB", "A100 (All variants)"]
        st.session_state["selected_gpus_key"] = initial_gpus

    col_g1, col_g2, col_g3 = st.columns(3)
    with col_g1:
        if st.button("✨ Всі карти", use_container_width=True, help="Обрати всі доступні моделі GPU"):
            st.session_state["selected_gpus_key"] = list(GPU_PRESETS)
            st.rerun()
    with col_g2:
        if st.button("🔥 Топ GPU", use_container_width=True, help="Обрати найпопулярніші моделі"):
            st.session_state["selected_gpus_key"] = ["RTX 4090", "RTX 3090", "RTX 5090", "Tesla V100 16GB", "Tesla V100 32GB", "A100 (All variants)", "H100 (All variants)"]
            st.rerun()
    with col_g3:
        if st.button("❌ Скинути", use_container_width=True, help="Очистити вибір карт"):
            st.session_state["selected_gpus_key"] = []
            st.rerun()

    selected_gpus = st.multiselect(
        "Моделі GPU:",
        options=GPU_PRESETS,
        key="selected_gpus_key",
        help="Оберіть одну або декілька моделей відеокарт. Доступні всі 85+ моделей ринку Vast.ai.",
    )

    # Configuration selection (1, 2, 4, 8 GPUs)
    st.markdown("#### 🧩 Кількість GPU у сервері")
    default_configs = saved_prefs.get("selected_configs", [1, 2, 4, 8])
    selected_configs = st.multiselect(
        "Конфігурація (кількість карт):",
        options=[1, 2, 4, 8],
        default=default_configs,
        format_func=lambda x: f"{x}x GPU",
    )

    # Price Mode
    st.markdown("#### 💲 Режим відображення ціни")
    mode_options = ["per_gpu", "per_instance"]
    saved_mode = saved_prefs.get("price_mode", "per_gpu")
    mode_idx = mode_options.index(saved_mode) if saved_mode in mode_options else 0
    price_mode = st.radio(
        "Тип розрахунку:",
        options=mode_options,
        format_func=lambda x: "За 1 GPU ($/год)" if x == "per_gpu" else "За весь сервер ($/год)",
        index=mode_idx,
    )

    # Period Selection
    st.markdown("#### 📅 Період аналізу")
    period_options = ["1 день", "7 днів", "30 днів", "90 днів", "Власний діапазон"]
    saved_period = saved_prefs.get("preset_period", "7 днів")
    period_idx = period_options.index(saved_period) if saved_period in period_options else 1
    preset_period = st.selectbox(
        "Швидкий пресет:",
        options=period_options,
        index=period_idx,
    )

    # Save preferences automatically whenever user changes filters
    current_prefs = {
        "selected_gpus": selected_gpus,
        "selected_configs": selected_configs,
        "price_mode": price_mode,
        "preset_period": preset_period,
        "auto_refresh": auto_refresh,
        "custom_gpu_prices": st.session_state.get("custom_gpu_prices", {}),
        "custom_load_w": st.session_state.get("custom_load_w", {}),
        "custom_idle_w": st.session_state.get("custom_idle_w", {}),
        "calc_currency": st.session_state.get("calc_currency", "USD ($)"),
        "usd_uah_rate": st.session_state.get("usd_uah_rate", 41.5),
        "usd_cny_rate": st.session_state.get("usd_cny_rate", 7.25),
        "saved_column_orders": st.session_state.get("saved_column_orders", {}),
    }

    if current_prefs != saved_prefs:
        save_preferences(current_prefs)
        st.toast("💾 Налаштування та обрані карти збережено!", icon="✅")

    if preset_period == "1 день":
        days_back = 1
    elif preset_period == "7 днів":
        days_back = 7
    elif preset_period == "30 днів":
        days_back = 30
    elif preset_period == "90 днів":
        days_back = 90
    else:
        today = datetime.date.today()
        default_start = today - datetime.timedelta(days=7)
        date_range = st.date_input("Оберіть дати:", value=(default_start, today))
        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            days_back = max(1, (date_range[1] - date_range[0]).days)
        else:
            days_back = 7

    price_label = "$/год за 1 GPU" if price_mode == "per_gpu" else "$/год за сервер"
    price_col = "dph_per_gpu" if price_mode == "per_gpu" else "dph_total"

    # Database Info in Sidebar (at the very bottom)
    st.markdown("---")
    st.markdown("#### 💾 База даних (SQLite)")
    db_info = VastAIClient.get_db_stats_info()
    last_db_snap = db_info.get("last_snapshot")
    db_snap_relative = format_time_ago(last_db_snap)
    st.caption(
        f"• **Розмір БД:** {db_info['db_size_mb']} MB\n"
        f"• **Зрізів ринку:** {db_info['total_snapshots']}\n"
        f"• **Записів серверів:** {db_info['total_raw_rows']:,}\n"
        f"• **Останній зріз у БД:** {db_snap_relative} ({last_db_snap or '—'})\n"
        f"• **Часовий пояс:** Київ (UTC+3 / EEST)"
    )

    if st.button("💾 Записати зріз у БД зараз", use_container_width=True):
        client = VastAIClient(api_key=api_key_input)
        with st.spinner("Збереження датасету ринку в базу..."):
            fresh_df = client.fetch_all_selected_offers(selected_gpus=None)
            VastAIClient.record_full_dataset_snapshot(fresh_df)
            st.session_state["last_market_fetch_ts"] = get_kyiv_now()
            st.success("✅ Датасет успішно збережено в SQLite!")
            st.cache_data.clear()
            st.rerun()


# --- MAIN AREA ---
if "last_market_fetch_ts" not in st.session_state:
    st.session_state["last_market_fetch_ts"] = get_kyiv_now()

last_dt = st.session_state.get("last_market_fetch_ts", get_kyiv_now())
time_ago_str = format_time_ago(last_dt)

st.markdown('<div class="main-title">⚡ Vast.ai GPU Price & Utilization Monitor</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="sub-title">Моніторинг ринку хмарних GPU Vast.ai у реальному часі • 🕒 Останнє оновлення: <b>{time_ago_str}</b> ({last_dt.strftime("%H:%M:%S")} за Києвом)</div>',
    unsafe_allow_html=True,
)


# Fetch data with error handling
with st.spinner("Завантаження свіжих даних з Vast.ai API..."):
    try:
        raw_df = load_vast_data(api_key=api_key_input, selected_gpus_tuple=tuple(selected_gpus) if selected_gpus else ())
    except VastAuthError as e:
        st.error(f"❌ {e}")
        st.stop()
    except VastRateLimitError as e:
        st.warning(f"⚠️ {e}")
        st.stop()
    except VastConnectionError as e:
        st.error(f"🌐 {e}")
        st.stop()
    except Exception as e:
        st.error(f"❌ Неочікувана помилка при завантаженні даних: {e}")
        st.stop()

if raw_df.empty:
    st.warning("⚠️ Не знайдено жодних пропозицій через Vast.ai API або в кеші зберігається старий запит. Натисніть кнопку нижче для перезавантаження.")
    if st.button("🔄 Очистити кеш та оновити дані зараз", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.stop()

# Filter data based on user choices
filtered_df = VastAIClient.filter_offers(
    raw_df,
    selected_gpus=selected_gpus if selected_gpus else None,
    selected_configs=selected_configs if selected_configs else None,
)

if filtered_df.empty:
    st.warning("🔍 Для обраних GPU та конфігурацій наразі немає пропозицій на ринку. Спробуйте розширити фільтри у боковій панелі.")
    st.stop()

# Compute summary stats from 100% real data
summary_df = VastAIClient.calculate_summary_stats(filtered_df, price_mode=price_mode)

# Save actual snapshot into local SQLite history database (both raw offers & summary stats)
VastAIClient.record_raw_offers_snapshot(raw_df)
VastAIClient.record_real_snapshot(summary_df, price_mode=price_mode)

# Load real history points from SQLite
timeline_df = VastAIClient.get_real_history(
    selected_gpus=selected_gpus,
    price_mode=price_mode,
    days_back=days_back,
)

# Precompute historical summary for selected period
hist_summary_df = VastAIClient.get_historical_summary(
    selected_gpus=selected_gpus if selected_gpus else None,
    price_mode=price_mode,
    days_back=days_back,
    live_summary_df=summary_df,
)
# Precompute configuration-level summaries (1x, 2x, 4x, 8x GPU rigs)
live_config_summary_df = VastAIClient.calculate_summary_stats_by_config(filtered_df, price_mode=price_mode)
hist_config_summary_df = VastAIClient.get_historical_summary_by_config(
    selected_gpus=selected_gpus if selected_gpus else None,
    selected_configs=selected_configs if selected_configs else None,
    price_mode=price_mode,
    days_back=days_back,
    live_config_summary_df=live_config_summary_df,
)


# Top KPI Metric Cards
total_offers = len(filtered_df)
available_offers = int(filtered_df["rentable"].sum())
overall_utilization = round(((total_offers - available_offers) / total_offers * 100.0), 1) if total_offers > 0 else 0.0
min_market_price = filtered_df[price_col].min()
median_market_price = filtered_df[price_col].median()

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("📦 Всього серверів", f"{total_offers} шт", f"{available_offers} доступно")
with col2:
    st.metric("🔥 Утилізація ринку", f"{overall_utilization}%", f"{total_offers - available_offers} у роботі")
with col3:
    st.metric("🏷 Мін. ціна", f"${min_market_price:.4f}", price_label)
with col4:
    st.metric("📊 Медіанна ціна", f"${median_market_price:.4f}", price_label)

st.markdown("---")
# Inform user if any selected GPU has 0 active offers on the marketplace
if selected_gpus:
    found_gpus = set(filtered_df["display_name"].unique()) if not filtered_df.empty else set()
    missing_gpus = [g for g in selected_gpus if g not in found_gpus]
    if missing_gpus:
        st.info(
            f"ℹ️ **Зверніть увагу:** Для наступних обраних карт наразі немає активних серверів на маркетплейсі Vast.ai: "
            f"**{', '.join(missing_gpus)}** (0 пропозицій на ринку). "
            f"Вони автоматично з'являться в графіках і таблицях, щойно хости виставлять сервери з цими картами."
        )


# Main Analysis Tabs
tab_price, tab_util, tab_profit, tab_machines, tab_summary, tab_offers, tab_history = st.tabs([
    "📈 Динаміка цін (P10 / Медіана / P90)",
    "⚡ Утилізація та доступність",
    "💰 Дохідність та ROI",
    "🏢 Хостери та машини (Host & Machine ID)",
    "📋 Зведена таблиця",
    "🔍 Детальні пропозиції (Live)",
    "💾 Історичний датасет (SQLite)",
])

with tab_price:
    st.markdown(f"#### 📊 Тренди цін та середні значення за обраний період ({days_back} днів)")

    # Historical Price Averages KPI Banner
    if not hist_summary_df.empty:
        p_avg_median = hist_summary_df["Медіана ($/год)"].mean()
        p_avg_mean = hist_summary_df["Сер. ціна ($/год)"].mean()
        p_avg_p10 = hist_summary_df["P10 ($/год)"].mean()
        p_avg_p90 = hist_summary_df["P90 ($/год)"].mean()

        hp1, hp2, hp3, hp4 = st.columns(4)
        with hp1:
            st.metric(f"📊 Сер. Медіана ({days_back}д)", f"${p_avg_median:.4f}", price_label)
        with hp2:
            st.metric(f"📈 Сер. Ціна ({days_back}д)", f"${p_avg_mean:.4f}", price_label)
        with hp3:
            st.metric("📉 Сер. P10 (нижня межа)", f"${p_avg_p10:.4f}", price_label)
        with hp4:
            st.metric("🚀 Сер. P90 (верхня межа)", f"${p_avg_p90:.4f}", price_label)

        with st.expander(f"📋 Таблиця середніх цін за {days_back} днів за моделями GPU", expanded=False):
            st.dataframe(
                hist_summary_df[["Карта", "Медіана ($/год)", "Сер. ціна ($/год)", "P10 ($/год)", "P90 ($/год)", "Мін. ціна ($/год)", "Макс. ціна ($/год)", "К-сть вимірів"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Карта": "Модель GPU",
                    "Медіана ($/год)": st.column_config.NumberColumn(f"Сер. Медіана ({days_back}д)", format="$%.4f"),
                    "Сер. ціна ($/год)": st.column_config.NumberColumn(f"Сер. Ціна ({days_back}д)", format="$%.4f"),
                    "P10 ($/год)": st.column_config.NumberColumn("Сер. P10", format="$%.4f"),
                    "P90 ($/год)": st.column_config.NumberColumn("Сер. P90", format="$%.4f"),
                    "Мін. ціна ($/год)": st.column_config.NumberColumn("Мін. за період", format="$%.4f"),
                    "Макс. ціна ($/год)": st.column_config.NumberColumn("Макс. за період", format="$%.4f"),
                    "К-сть вимірів": "К-сть зрізів",
                },
            )

    if timeline_df.empty:
        st.info("ℹ️ Запис історії щойно розпочато. Графік тренду будуватиметься автоматично з накопиченням зрізів ринку кожні 5 хвилин.")

    col_chart1, col_chart2 = st.columns([3, 2])
    with col_chart1:
        price_line_fig = create_price_line_chart(timeline_df, price_label, hist_summary_df)
        st.plotly_chart(price_line_fig, use_container_width=True)
    with col_chart2:
        price_box_fig = create_price_box_chart(filtered_df, price_col, price_label)
        st.plotly_chart(price_box_fig, use_container_width=True)


with tab_util:
    st.markdown(f"#### ⚡ Рівень зайнятості та доступності (Live vs Сер. за {days_back} днів)")

    util_breakdown_tab = st.radio(
        "Розріз аналізу утилізації:",
        ["📊 Загальний за моделями GPU", "🧩 В розрізі конфігурацій (1x, 2x, 4x, 8x карт)"],
        horizontal=True,
        key="util_breakdown_tab_sel",
    )

    if "Загальний" in util_breakdown_tab:
        # Historical Utilization KPI Banner
        if not hist_summary_df.empty:
            u_avg_period = hist_summary_df["Утилізація (%)"].mean()
            u_min_period = hist_summary_df["Мін. утилізація (%)"].min() if "Мін. утилізація (%)" in hist_summary_df.columns else hist_summary_df["Утилізація (%)"].min()
            u_max_period = hist_summary_df["Макс. утилізація (%)"].max() if "Макс. утилізація (%)" in hist_summary_df.columns else hist_summary_df["Утилізація (%)"].max()

            hu1, hu2, hu3, hu4 = st.columns(4)
            with hu1:
                st.metric(f"🔥 Сер. утилізація ({days_back}д)", f"{u_avg_period:.1f}%", f"Live: {overall_utilization}%")
            with hu2:
                st.metric("📉 Мін. утилізація за період", f"{u_min_period:.1f}%")
            with hu3:
                st.metric("🚀 Макс. утилізація за період", f"{u_max_period:.1f}%")
            with hu4:
                top_busy_gpu = hist_summary_df.sort_values(by="Утилізація (%)", ascending=False).iloc[0]
                st.metric(f"🏆 Топ завантаження ({days_back}д)", f"{top_busy_gpu['Карта']}", f"{top_busy_gpu['Утилізація (%)']:.1f}%")

            with st.expander(f"📋 Порівняльна таблиця утилізації: Поточна vs Середня за {days_back} днів", expanded=False):
                util_compare_cols = ["Карта", "Утилізація (%)"]
                if "Мін. утилізація (%)" in hist_summary_df.columns:
                    util_compare_cols += ["Мін. утилізація (%)", "Макс. утилізація (%)"]
                util_compare_cols += ["Доступно (шт)", "Всього серверів (шт)", "К-сть вимірів"]

                util_compare_df = hist_summary_df[util_compare_cols].copy()
                util_compare_df = util_compare_df.rename(columns={"Утилізація (%)": f"Сер. утилізація ({days_back}д, %)"})
                live_util_map = dict(zip(summary_df["Карта"], summary_df["Утилізація (%)"]))
                util_compare_df.insert(2, "Поточна Live (%)", util_compare_df["Карта"].map(live_util_map).fillna(0.0))

                st.dataframe(
                    util_compare_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Карта": "Модель GPU",
                        f"Сер. утилізація ({days_back}д, %)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
                        "Поточна Live (%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
                        "Мін. утилізація (%)": st.column_config.NumberColumn(format="%.1f%%"),
                        "Макс. утилізація (%)": st.column_config.NumberColumn(format="%.1f%%"),
                    },
                )

        col_ut1, col_ut2 = st.columns([3, 2])
        with col_ut1:
            st.plotly_chart(create_utilization_chart(summary_df, hist_summary_df, days_back), use_container_width=True)
        with col_ut2:
            if not timeline_df.empty:
                st.plotly_chart(create_utilization_timeline_chart(timeline_df, hist_summary_df), use_container_width=True)
            else:
                st.info("ℹ️ Історична динаміка утилізації формується автоматично з накопиченням зрізів у SQLite.")


        col_u1, col_u2 = st.columns(2)
        with col_u1:
            st.markdown("##### 🏎 Середня продуктивність DLPerf за моделями")
            dlperf_df = filtered_df.groupby("display_name")["dlperf"].mean().reset_index()
            dlperf_fig = px.bar(
                dlperf_df,
                x="display_name",
                y="dlperf",
                color="display_name",
                title="DLPerf Score (вища швидкість = краще)",
                template="plotly_dark",
            )
            dlperf_fig.update_layout(showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.6)")
            st.plotly_chart(dlperf_fig, use_container_width=True)

        with col_u2:
            st.markdown("##### 🛡 Надійність серверів (Reliability %)")
            rel_df = filtered_df.groupby("display_name")["reliability_pct"].mean().reset_index()
            rel_fig = px.bar(
                rel_df,
                x="display_name",
                y="reliability_pct",
                color="display_name",
                title="Середній рейтинг надійності (%)",
                template="plotly_dark",
            )
            rel_fig.update_layout(showlegend=False, yaxis=dict(range=[70, 100]), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.6)")
            st.plotly_chart(rel_fig, use_container_width=True)
    else:

        # Configuration breakdown view (1x, 2x, 4x, 8x GPU)
        st.markdown("##### 🧩 Порівняння утилізації за кількістю GPU у сервері (1x / 2x / 4x / 8x)")
        
        cfg_chart = create_config_utilization_chart(live_config_summary_df)
        st.plotly_chart(cfg_chart, use_container_width=True)

        st.markdown("##### 📋 Зведена статистика утилізації в розрізі конфігурацій")
        cfg_util_order = render_column_order_selector("config_util_table", list(live_config_summary_df.columns))
        st.dataframe(
            live_config_summary_df,
            column_order=cfg_util_order,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Конфігурація": st.column_config.TextColumn("Конфігурація", width="medium"),
                "Карта": "Модель GPU",
                "К-сть GPU": "Карт (шт)",
                "Утилізація (%)": st.column_config.ProgressColumn("Утилізація", min_value=0, max_value=100, format="%.1f%%"),
                "Доступно (шт)": st.column_config.NumberColumn(format="%d"),
                "Всього серверів (шт)": st.column_config.NumberColumn(format="%d"),
                "Медіана ($/год)": st.column_config.NumberColumn(f"Медіана ({price_label})", format="$%.4f"),
                "Сер. ціна ($/год)": st.column_config.NumberColumn(f"Сер. ціна ({price_label})", format="$%.4f"),
                "Мін. ціна ($/год)": st.column_config.NumberColumn(format="$%.4f"),
                "Макс. ціна ($/год)": st.column_config.NumberColumn(format="$%.4f"),
            },
        )




with tab_profit:
    st.markdown("#### 💰 Максимально реалістичний калькулятор дохідності хоста (Host ROI)")
    st.caption("Розрахунок базується на реальних ринкових цінах оренди Vast.ai, фактичному рівні завантаженості та повному енергоспоживанні (навантаження / простій).")

    # Profitability Settings & Source Selection
    st.markdown("##### ⚙️ Параметри розрахунку")
    calc_col1, calc_col2 = st.columns([2, 1])
    with calc_col1:
        roi_data_source = st.radio(
            "📊 Джерело ринкових даних (ціна та утилізація):",
            [
                f"📈 Історичні середні за період ({days_back} днів) — рекомендовано для згладжування сплесків",
                "⚡ Поточний Live-зріз ринку",
            ],
            index=0,
            horizontal=True,
        )
    with calc_col2:
        price_metric_choice = st.selectbox(
            "🏷 Метрика ціни оренди:",
            ["Медіана ($/год)", "Сер. ціна ($/год)", "P10 ($/год)", "P90 ($/год)"],
            index=0,
            help="Медіана (P50) є найбільш репрезентативною, P10 — для агресивного демпінгу, P90 — оптимістичний сценарій.",
        )

    # Economic parameters
    pcol1, pcol2, pcol3, pcol4 = st.columns(4)
    with pcol1:
        elec_cost_input = st.number_input(
            "⚡ Тариф на світло ($/кВт·год):",
            min_value=0.0,
            max_value=1.0,
            value=0.08,
            step=0.01,
            format="%.3f",
            help="Вартість електроенергії за 1 кВт·год (за замовчуванням $0.08)",
        )
    with pcol2:
        platform_fee_input = st.number_input(
            "🤝 Комісія Vast.ai (%):",
            min_value=0.0,
            max_value=30.0,
            value=10.0,
            step=1.0,
            help="Відсоток комісії платформи на виплати хостам (за замовчуванням 10%)",
        )
    with pcol3:
        psu_efficiency_input = st.slider(
            "🔌 ККД БЖ (PSU Efficiency %):",
            min_value=70,
            max_value=100,
            value=90,
            step=1,
            help="Коефіцієнт корисної дії блоку живлення (80 Plus Gold/Platinum ~ 90%)",
        )
    with pcol4:
        fixed_cost_input = st.number_input(
            "🏢 Фікс. витрати ($/міс на карту):",
            min_value=0.0,
            max_value=500.0,
            value=0.0,
            step=5.0,
            help="Інтернет, статичний IP, оренда юніту або амортизація серверної",
        )

    with st.expander("🔧 Додаткові параметри енергоспоживання платформи", expanded=False):
        ecol1, ecol2 = st.columns(2)
        with ecol1:
            host_load_w = st.number_input(
                "Базове навантаження платформи під час роботи (Вт на карту):",
                min_value=0,
                max_value=500,
                value=60,
                step=5,
                help="Споживання CPU, RAM, материнської плати та вентиляторів у розрахунку на 1 GPU під навантаженням",
            )
        with ecol2:
            host_idle_w = st.number_input(
                "Базове споживання платформи у простої (Вт на карту):",
                min_value=0,
                max_value=300,
                value=30,
                step=5,
                help="Споживання сервера у стані очікування без активних завдань",
            )

    # Prepare base summary data
    if "Історичні середні" in roi_data_source:
        base_calc_summary = VastAIClient.get_historical_summary(
            selected_gpus=selected_gpus if selected_gpus else None,
            price_mode=price_mode,
            days_back=days_back,
            live_summary_df=summary_df,
        )
    else:
        base_calc_summary = summary_df.copy()

    calc_scope_mode = st.radio(
        "🔍 Режим розрахунку прибутковості:",
        ["👤 Поодинокі карти (на 1 GPU)", "🖥 Готові сервери / риги (1x, 2x, 4x, 8x GPU)"],
        horizontal=True,
        key="roi_calc_scope_radio",
    )

    # Hardware purchase prices and TDP editor
    st.markdown("##### 🛠 Вартість обладнання ($ / ₴ / ¥) та енергоспоживання (Вт)")

    # Currency selection & conversion rates
    curr_col1, curr_col2, curr_col3 = st.columns([2, 1.5, 1.5])
    with curr_col1:
        curr_options = ["USD ($)", "UAH (₴ - Гривня)", "CNY (¥ - Юань)"]
        curr_saved = st.session_state.get("calc_currency", "USD ($)")
        curr_idx = curr_options.index(curr_saved) if curr_saved in curr_options else 0
        calc_currency = st.radio(
            "💱 Валюта введення вартості карт:",
            curr_options,
            index=curr_idx,
            horizontal=True,
            key="calc_currency_radio",
        )
        st.session_state["calc_currency"] = calc_currency

    with curr_col2:
        uah_rate = st.number_input(
            "Курс USD/UAH (₴ / $1):",
            min_value=1.0,
            max_value=100.0,
            value=float(st.session_state.get("usd_uah_rate", 41.5)),
            step=0.1,
            format="%.2f",
            key="rate_uah_input",
            help="Курс гривні до долара для автоперерахунку",
        )
        st.session_state["usd_uah_rate"] = uah_rate

    with curr_col3:
        cny_rate = st.number_input(
            "Курс USD/CNY (¥ / $1):",
            min_value=1.0,
            max_value=30.0,
            value=float(st.session_state.get("usd_cny_rate", 7.25)),
            step=0.05,
            format="%.2f",
            key="rate_cny_input",
            help="Курс юаня до долара для покупок з Китаю (Taobao / Alibaba)",
        )
        st.session_state["usd_cny_rate"] = cny_rate

    avail_gpus_calc = list(base_calc_summary["Карта"]) if not base_calc_summary.empty else []

    # Quick single card input
    if avail_gpus_calc:
        col_edit_hdr, col_reset_btn = st.columns([4, 1])
        with col_edit_hdr:
            st.markdown(f"###### 🎯 Швидкий ввід ціни у **{calc_currency}**:")
        with col_reset_btn:
            if st.button("🔄 Скинути дефолт", help="Скинути всі кастомні ціни до ринкових за замовчуванням"):
                st.session_state["custom_gpu_prices"] = {}
                st.session_state["custom_load_w"] = {}
                st.session_state["custom_idle_w"] = {}
                save_preferences({
                    "custom_gpu_prices": {},
                    "custom_load_w": {},
                    "custom_idle_w": {},
                    "calc_currency": calc_currency,
                    "usd_uah_rate": uah_rate,
                    "usd_cny_rate": cny_rate,
                })
                st.rerun()

        cq1, cq2, cq3, cq4 = st.columns([2, 1.5, 1.5, 1.5])
        with cq1:
            selected_edit_gpu = st.selectbox("Оберіть GPU зі списку:", options=avail_gpus_calc, key="quick_edit_gpu_sel")

        def_specs_for_sel = get_gpu_specs(selected_edit_gpu)
        curr_val_usd = float(st.session_state["custom_gpu_prices"].get(selected_edit_gpu, def_specs_for_sel["price_usd"]))
        curr_val_lw = int(st.session_state["custom_load_w"].get(selected_edit_gpu, def_specs_for_sel["load_w"]))
        curr_val_iw = int(st.session_state["custom_idle_w"].get(selected_edit_gpu, def_specs_for_sel["idle_w"]))

        if "UAH" in calc_currency:
            curr_val_local = curr_val_usd * uah_rate
            local_step = 1000.0
            local_label = f"Ціна {selected_edit_gpu} (₴ грн):"
        elif "CNY" in calc_currency:
            curr_val_local = curr_val_usd * cny_rate
            local_step = 200.0
            local_label = f"Ціна {selected_edit_gpu} (¥ юань):"
        else:
            curr_val_local = curr_val_usd
            local_step = 50.0
            local_label = f"Ціна {selected_edit_gpu} ($ USD):"

        with cq2:
            in_price_local = st.number_input(
                local_label,
                min_value=0.0,
                max_value=10000000.0,
                value=float(curr_val_local),
                step=local_step,
                format="%.0f",
                key=f"num_p_{selected_edit_gpu}_{calc_currency}",
            )
            if "UAH" in calc_currency:
                in_price_usd = round(in_price_local / uah_rate, 1)
                st.caption(f"≈ **${in_price_usd:,.0f} USD** (курс {uah_rate:.2f} ₴/$)")
            elif "CNY" in calc_currency:
                in_price_usd = round(in_price_local / cny_rate, 1)
                st.caption(f"≈ **${in_price_usd:,.0f} USD** (курс {cny_rate:.2f} ¥/$)")
            else:
                in_price_usd = in_price_local

            if abs(in_price_usd - curr_val_usd) > 0.5:
                st.session_state["custom_gpu_prices"][selected_edit_gpu] = in_price_usd
                save_preferences({
                    "custom_gpu_prices": st.session_state["custom_gpu_prices"],
                    "calc_currency": calc_currency,
                    "usd_uah_rate": uah_rate,
                    "usd_cny_rate": cny_rate,
                })
                st.rerun()

        with cq3:
            in_lw = st.number_input(
                "TDP Load (Вт):",
                min_value=10,
                max_value=2000,
                value=curr_val_lw,
                step=10,
                key=f"num_lw_{selected_edit_gpu}",
            )
            if in_lw != curr_val_lw:
                st.session_state["custom_load_w"][selected_edit_gpu] = in_lw
                save_preferences({"custom_load_w": st.session_state["custom_load_w"]})
                st.rerun()

        with cq4:
            in_iw = st.number_input(
                "TDP Idle (Вт):",
                min_value=5,
                max_value=500,
                value=curr_val_iw,
                step=5,
                key=f"num_iw_{selected_edit_gpu}",
            )
            if in_iw != curr_val_iw:
                st.session_state["custom_idle_w"][selected_edit_gpu] = in_iw
                save_preferences({"custom_idle_w": st.session_state["custom_idle_w"]})
                st.rerun()



    # Method 2: Multi-row Table Editor
    if "UAH" in calc_currency:
        price_col_name = "Ціна купівлі (₴ грн)"
        conv_factor = uah_rate
        price_fmt = "₴%.0f"
        price_min = 0.0
        price_step = 1000.0
    elif "CNY" in calc_currency:
        price_col_name = "Ціна купівлі (¥ юань)"
        conv_factor = cny_rate
        price_fmt = "¥%.0f"
        price_min = 0.0
        price_step = 200.0
    else:
        price_col_name = "Ціна купівлі ($ USD)"
        conv_factor = 1.0
        price_fmt = "$%.0f"
        price_min = 0.0
        price_step = 50.0

    edit_rows = []
    for _, r in base_calc_summary.iterrows():
        gname = str(r["Карта"])
        specs = get_gpu_specs(gname)
        g_price_usd = float(st.session_state["custom_gpu_prices"].get(gname, specs["price_usd"]))
        g_price_local = float(round(g_price_usd * conv_factor, 0))
        g_lw = int(st.session_state["custom_load_w"].get(gname, specs["load_w"]))
        g_iw = int(st.session_state["custom_idle_w"].get(gname, specs["idle_w"]))

        row_dict = {
            "Карта": gname,
            price_col_name: g_price_local,
            "TDP Навантаження (Вт)": g_lw,
            "TDP Простій (Вт)": g_iw,
            "Утилізація (%)": float(r.get("Утилізація (%)", 0.0)),
            "Оренда ($/год)": float(r.get(price_metric_choice, r.get("Медіана ($/год)", 0.0))),
        }
        if conv_factor != 1.0:
            row_dict["Ціна в USD ($)"] = g_price_usd
        edit_rows.append(row_dict)

    specs_df = pd.DataFrame(edit_rows)

    with st.expander(f"📝 Редагувати всі карти одночасно у таблиці (у {calc_currency})", expanded=True):
        col_cfg = {
            "Карта": st.column_config.TextColumn("Модель GPU", width="medium"),
            price_col_name: st.column_config.NumberColumn(f"Вартість ({calc_currency.split()[0]})", min_value=price_min, step=price_step, format=price_fmt),
            "TDP Навантаження (Вт)": st.column_config.NumberColumn("TDP Load (W)", min_value=10, max_value=1500, step=10),
            "TDP Простій (Вт)": st.column_config.NumberColumn("TDP Idle (W)", min_value=5, max_value=500, step=5),
            "Утилізація (%)": st.column_config.ProgressColumn("Утилізація", min_value=0, max_value=100, format="%.1f%%"),
            "Оренда ($/год)": st.column_config.NumberColumn("Ставка оренди", format="$%.4f"),
        }
        if conv_factor != 1.0:
            col_cfg["Ціна в USD ($)"] = st.column_config.NumberColumn("Еквівалент USD ($)", format="$%.0f")

        disabled_cols = ["Карта", "Утилізація (%)", "Оренда ($/год)"]
        if conv_factor != 1.0:
            disabled_cols.append("Ціна в USD ($)")

        edited_specs = st.data_editor(
            specs_df,
            use_container_width=True,
            hide_index=True,
            disabled=disabled_cols,
            column_config=col_cfg,
            key=f"roi_specs_editor_table_{calc_currency}",
        )

        # Sync any cell edits in data_editor to session_state
        if edited_specs is not None and not edited_specs.empty:
            has_changes = False
            for _, erow in edited_specs.iterrows():
                egpu = str(erow["Карта"])
                eprice_local = float(erow[price_col_name])
                eprice_usd = round(eprice_local / conv_factor, 1)
                elw = int(erow["TDP Навантаження (Вт)"])
                eiw = int(erow["TDP Простій (Вт)"])

                if abs(st.session_state["custom_gpu_prices"].get(egpu, 0.0) - eprice_usd) > 0.5:
                    st.session_state["custom_gpu_prices"][egpu] = eprice_usd
                    has_changes = True
                if st.session_state["custom_load_w"].get(egpu) != elw:
                    st.session_state["custom_load_w"][egpu] = elw
                    has_changes = True
                if st.session_state["custom_idle_w"].get(egpu) != eiw:
                    st.session_state["custom_idle_w"][egpu] = eiw
                    has_changes = True

            if has_changes:
                save_preferences({
                    "custom_gpu_prices": st.session_state["custom_gpu_prices"],
                    "custom_load_w": st.session_state["custom_load_w"],
                    "custom_idle_w": st.session_state["custom_idle_w"],
                    "calc_currency": calc_currency,
                    "usd_uah_rate": uah_rate,
                    "usd_cny_rate": cny_rate,
                })

    custom_prices_map = st.session_state["custom_gpu_prices"]
    custom_load_map = st.session_state["custom_load_w"]
    custom_idle_map = st.session_state["custom_idle_w"]



    if "Поодинокі карти" in calc_scope_mode:
        roi_result_df = calculate_roi_table(
            summary_df=base_calc_summary,
            custom_prices=custom_prices_map,
            custom_load_w=custom_load_map,
            custom_idle_w=custom_idle_map,
            electricity_kwh_cost=elec_cost_input,
            host_system_load_w=host_load_w,
            host_system_idle_w=host_idle_w,
            psu_efficiency=psu_efficiency_input / 100.0,
            platform_fee_pct=platform_fee_input,
            monthly_fixed_cost=fixed_cost_input,
            price_metric=price_metric_choice,
        )

        if not roi_result_df.empty:
            st.markdown("##### 🏆 Ключові показники прибутковості")
            best_profit_row = roi_result_df.sort_values(by="Чистий прибуток ($/міс)", ascending=False).iloc[0]

            profitable_cards = roi_result_df[pd.notnull(roi_result_df["Окупність (місяців)"])].copy()
            if not profitable_cards.empty:
                profitable_cards["pay_num"] = pd.to_numeric(profitable_cards["Окупність (місяців)"], errors="coerce")
                profitable_cards = profitable_cards.dropna(subset=["pay_num"])
                if not profitable_cards.empty:
                    best_payback_row = profitable_cards.sort_values(by="pay_num", ascending=True).iloc[0]
                    best_payback_text = f"{best_payback_row['Карта']} ({best_payback_row['pay_num']:.1f} міс.)"
                else:
                    best_payback_text = "—"
            else:
                best_payback_text = "—"

            avg_roi_val = roi_result_df["Річний ROI (%)"].mean()
            avg_power_cost = roi_result_df["Світло ($/міс)"].mean()

            rk1, rk2, rk3, rk4 = st.columns(4)
            with rk1:
                st.metric("💎 Топ за прибутком", f"{best_profit_row['Карта']}", f"+${best_profit_row['Чистий прибуток ($/міс)']:.2f} / міс")
            with rk2:
                st.metric("⚡ Найшвидша окупність", best_payback_text)
            with rk3:
                st.metric("📈 Сер. річний ROI", f"{avg_roi_val:.1f}%", "по обраних моделях")
            with rk4:
                st.metric("💡 Сер. рахунок за світло", f"${avg_power_cost:.2f}", "/ міс на 1 GPU")

            rchart1, rchart2 = st.columns([3, 2])
            with rchart1:
                st.plotly_chart(create_roi_financials_chart(roi_result_df), use_container_width=True)
            with rchart2:
                st.plotly_chart(create_roi_payback_chart(roi_result_df), use_container_width=True)

            st.markdown("##### 📋 Детальна фінансова таблиця окупності")
            roi_single_order = render_column_order_selector("roi_single_table", list(roi_result_df.columns))
            st.dataframe(
                roi_result_df,
                column_order=roi_single_order,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Карта": st.column_config.TextColumn("Модель GPU", width="medium"),
                    "Ціна карти ($)": st.column_config.NumberColumn(format="$%.0f"),
                    "Оренда ($/год)": st.column_config.NumberColumn(format="$%.4f"),
                    "Утилізація (%)": st.column_config.ProgressColumn("Утилізація", min_value=0, max_value=100, format="%.1f%%"),
                    "Споживання під навантаженням (Вт)": st.column_config.NumberColumn(format="%d W"),
                    "Споживання в простої (Вт)": st.column_config.NumberColumn(format="%d W"),
                    "Світло ($/міс)": st.column_config.NumberColumn(format="$%.2f"),
                    "Валовий дохід ($/міс)": st.column_config.NumberColumn(format="$%.2f"),
                    "Чистий прибуток ($/день)": st.column_config.NumberColumn(format="$%.2f"),
                    "Чистий прибуток ($/міс)": st.column_config.NumberColumn(format="$%.2f"),
                    "Чистий прибуток ($/рік)": st.column_config.NumberColumn(format="$%.2f"),
                    "Окупність (місяців)": st.column_config.NumberColumn("Окупність (міс.)", format="%.1f", help="Термін окупності у місяцях"),
                    "Окупність (днів)": st.column_config.NumberColumn("Окупність (днів)", format="%d", help="Термін окупності у днях"),
                    "Річний ROI (%)": st.column_config.NumberColumn(format="%.1f%%"),
                    "Маржа (%)": st.column_config.NumberColumn(format="%.1f%%"),
                    "Граничне світло ($/кВт·год)": st.column_config.NumberColumn(format="$%.4f", help="Максимальна ціна за кВт·год, при якій хостинг залишається беззбитковим"),
                    "Мін. утилізація (%)": st.column_config.NumberColumn(format="%.1f%%", help="Мінімальний відсоток зайнятості для покриття рахунку за електроенергію"),
                },
            )


            csv_roi = roi_result_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Експорт розрахунків дохідності та ROI у CSV",
                data=csv_roi,
                file_name=f"vast_gpu_roi_analysis_{datetime.date.today()}.csv",
                mime="text/csv",
                use_container_width=True,
            )

    else:
        # Multi-GPU Server Rig calculation mode
        st.markdown("##### 🖥 Розрахунок дохідності та окупності багатокарточних серверів (Рігів)")
        st.caption("Враховує повну вартість ригу (N відеокарт + платформа) та фактичну утилізацію конкретної конфігурації (1x, 2x, 4x, 8x GPU).")

        with st.expander("🛠 Налаштування вартості платформи серверів (MB + CPU + RAM + PSUs + Корпус)", expanded=False):
            pc1, pc2, pc3, pc4 = st.columns(4)
            with pc1:
                plat_cost_1 = st.number_input("Платформа 1x GPU ($):", min_value=0.0, max_value=5000.0, value=350.0, step=50.0, key="plat_1_cost")
            with pc2:
                plat_cost_2 = st.number_input("Платформа 2x GPU ($):", min_value=0.0, max_value=10000.0, value=550.0, step=50.0, key="plat_2_cost")
            with pc3:
                plat_cost_4 = st.number_input("Платформа 4x GPU ($):", min_value=0.0, max_value=20000.0, value=950.0, step=50.0, key="plat_4_cost")
            with pc4:
                plat_cost_8 = st.number_input("Платформа 8x GPU ($):", min_value=0.0, max_value=30000.0, value=1700.0, step=100.0, key="plat_8_cost")
            custom_plat_costs = {1: plat_cost_1, 2: plat_cost_2, 4: plat_cost_4, 8: plat_cost_8}

        if "Історичні середні" in roi_data_source:
            base_calc_cfg_summary = hist_config_summary_df.copy()
        else:
            base_calc_cfg_summary = live_config_summary_df.copy()

        config_roi_df = calculate_roi_table_by_config(
            config_summary_df=base_calc_cfg_summary,
            custom_prices=custom_prices_map,
            custom_load_w=custom_load_map,
            custom_idle_w=custom_idle_map,
            custom_platform_costs=custom_plat_costs,
            electricity_kwh_cost=elec_cost_input,
            psu_efficiency=psu_efficiency_input / 100.0,
            platform_fee_pct=platform_fee_input,
            monthly_fixed_cost_per_server=fixed_cost_input,
            price_metric=price_metric_choice,
        )

        if not config_roi_df.empty:
            st.markdown("##### 🏆 Ключові показники прибутковості серверів/ригів")
            best_cfg_profit = config_roi_df.sort_values(by="Чистий прибуток ($/міс)", ascending=False).iloc[0]

            prof_cfgs = config_roi_df[pd.notnull(config_roi_df["Окупність (місяців)"])].copy()
            if not prof_cfgs.empty:
                prof_cfgs["pay_num"] = pd.to_numeric(prof_cfgs["Окупність (місяців)"], errors="coerce")
                prof_cfgs = prof_cfgs.dropna(subset=["pay_num"])
                if not prof_cfgs.empty:
                    best_cfg_payback = prof_cfgs.sort_values(by="pay_num", ascending=True).iloc[0]
                    best_cfg_payback_text = f"{best_cfg_payback['Конфігурація']} ({best_cfg_payback['pay_num']:.1f} міс.)"
                    best_cfg_roi = prof_cfgs.sort_values(by="Річний ROI (%)", ascending=False).iloc[0]
                    best_cfg_roi_text = f"{best_cfg_roi['Конфігурація']} ({best_cfg_roi['Річний ROI (%)']}%)"
                else:
                    best_cfg_payback_text = "—"
                    best_cfg_roi_text = "—"
            else:
                best_cfg_payback_text = "—"
                best_cfg_roi_text = "—"

            avg_rig_power = config_roi_df["Світло ($/міс)"].mean()

            rkc1, rkc2, rkc3, rkc4 = st.columns(4)
            with rkc1:
                st.metric("💎 Найприбутковіший сервер", f"{best_cfg_profit['Конфігурація']}", f"+${best_cfg_profit['Чистий прибуток ($/міс)']:.2f} / міс")
            with rkc2:
                st.metric("⚡ Найшвидша окупність ригу", best_cfg_payback_text)
            with rkc3:
                st.metric("📈 Топ ROI серед конфігурацій", best_cfg_roi_text)
            with rkc4:
                st.metric("💡 Сер. рахунок за світло ригу", f"${avg_rig_power:.2f}", "/ міс на сервер")

            st.plotly_chart(create_config_roi_profit_chart(config_roi_df), use_container_width=True)

            st.markdown("##### 📋 Детальна фінансова таблиця серверних конфігурацій")
            cfg_roi_order = render_column_order_selector("config_roi_table", list(config_roi_df.columns))
            st.dataframe(
                config_roi_df,
                column_order=cfg_roi_order,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Конфігурація": st.column_config.TextColumn("Конфігурація", width="medium"),
                    "Вартість сервера ($)": st.column_config.NumberColumn(format="$%.0f"),
                    "Ціна карти ($)": st.column_config.NumberColumn(format="$%.0f"),
                    "Ціна платформи ($)": st.column_config.NumberColumn(format="$%.0f"),
                    "Оренда / 1 GPU ($/год)": st.column_config.NumberColumn(format="$%.4f"),
                    "Оренда сервера ($/год)": st.column_config.NumberColumn(format="$%.4f"),
                    "Утилізація (%)": st.column_config.ProgressColumn("Утилізація", min_value=0, max_value=100, format="%.1f%%"),
                    "Споживання сервера (Вт)": st.column_config.NumberColumn(format="%d W"),
                    "Світло ($/міс)": st.column_config.NumberColumn(format="$%.2f"),
                    "Валовий дохід ($/міс)": st.column_config.NumberColumn(format="$%.2f"),
                    "Чистий прибуток ($/день)": st.column_config.NumberColumn(format="$%.2f"),
                    "Чистий прибуток ($/міс)": st.column_config.NumberColumn(format="$%.2f"),
                    "Чистий прибуток ($/рік)": st.column_config.NumberColumn(format="$%.2f"),
                    "Окупність (місяців)": st.column_config.NumberColumn("Окупність (міс.)", format="%.1f", help="Термін окупності у місяцях"),
                    "Окупність (днів)": st.column_config.NumberColumn("Окупність (днів)", format="%d", help="Термін окупності у днях"),
                    "Річний ROI (%)": st.column_config.NumberColumn(format="%.1f%%"),
                    "Маржа (%)": st.column_config.NumberColumn(format="%.1f%%"),
                    "Всього серверів (шт)": st.column_config.NumberColumn(format="%d"),
                },
            )


            csv_cfg_roi = config_roi_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Експорт розрахунків дохідності конфігурацій (ригів) у CSV",
                data=csv_cfg_roi,
                file_name=f"vast_gpu_rig_roi_analysis_{datetime.date.today()}.csv",
                mime="text/csv",
                use_container_width=True,
            )




with tab_machines:
    st.markdown("#### 🏢 Моніторинг хостерів (Host ID) та конкретних машин (Machine ID)")
    st.caption("Аналізуйте всі машини одного хостера (флот хоста) або окремі машини: історія цін оренди, фактичне заповнення (утилізація), оцінка заробітку та порівняння з ринком.")

    tracking_mode = st.radio(
        "Оберіть режим відстеження:",
        [
            "🏢 Відстеження всього флоту за Host ID (Всі машини хостера)",
            "🖥️ Відстеження за Machine ID (Окремі машини)",
        ],
        horizontal=True,
        index=0,
    )

    if "Host ID" in tracking_mode:
        st.markdown("##### 🏢 Відстеження всіх машин конкретного хостера")
        h_col1, h_col2, h_col3 = st.columns([2.5, 1.5, 1])
        with h_col1:
            current_watched_hosts = st.session_state.get("watched_host_ids", [69666])
            input_host_str = st.text_input(
                "Введіть Host ID (наприклад 69666 або декілька через кому):",
                value=", ".join(str(h) for h in current_watched_hosts),
                placeholder="Наприклад: 69666, 12841, 42830",
                help="Host ID хостера на Vast.ai. Будуть відображені всі машини та GPU, що належать цьому хостеру.",
            )
        with h_col2:
            try:
                all_hosts_db = VastAIClient.get_all_tracked_hosts_summary(days_back=days_back)
            except Exception:
                all_hosts_db = pd.DataFrame()
            quick_host_options = ["— Оберіть популярного хостера з БД —"]
            if not all_hosts_db.empty:
                for _, hrow in all_hosts_db.head(25).iterrows():
                    quick_host_options.append(f"Host #{hrow['host_id']} — {hrow['total_machines']} машин | Заповн: {hrow['occupancy_pct']}% | {hrow['geolocation']}")
            quick_host_picked = st.selectbox("Швидкий вибір хостера з БД:", options=quick_host_options, index=0)

        with h_col3:
            host_days_back = st.selectbox(
                "Період аналізу флоту:",
                [1, 3, 7, 14, 30, 60],
                index=2,
                format_func=lambda d: f"{d} дн" if d != 1 else "24 год",
                key="host_days_back_select",
            )

        # Parse host IDs
        parsed_host_ids = []
        for token in input_host_str.replace(";", ",").replace(" ", ",").split(","):
            token = token.strip()
            if token.isdigit():
                val = int(token)
                if val not in parsed_host_ids:
                    parsed_host_ids.append(val)

        if quick_host_picked != "— Оберіть популярного хостера з БД —":
            try:
                picked_hid = int(quick_host_picked.split()[1].replace("#", ""))
                if picked_hid not in parsed_host_ids:
                    parsed_host_ids.append(picked_hid)
            except Exception:
                pass

        if parsed_host_ids != current_watched_hosts:
            st.session_state["watched_host_ids"] = parsed_host_ids
            save_preferences({"watched_host_ids": parsed_host_ids})

        if not parsed_host_ids:
            st.info("ℹ️ Введіть Host ID у поле вище для відображення всіх його машин.")
        else:
            if len(parsed_host_ids) > 1:
                primary_host_id = st.selectbox(
                    "Оберіть Host ID для детального перегляду:",
                    options=parsed_host_ids,
                    format_func=lambda hid: f"Host #{hid}",
                    key="active_host_id_select"
                )
            else:
                primary_host_id = parsed_host_ids[0]

            col_h_act1, col_h_act2 = st.columns([1.8, 4])
            with col_h_act1:
                refresh_host_btn = st.button("🔄 Оновити флот з Vast.ai API", key="refresh_host_api_btn", use_container_width=True)

            try:
                host_hist_df = VastAIClient.get_host_history(host_ids=[primary_host_id], days_back=host_days_back)
            except Exception:
                host_hist_df = pd.DataFrame()

            if host_hist_df.empty or refresh_host_btn:
                with st.spinner(f"⚡ Отримання свіжих даних флоту Host #{primary_host_id} з Vast.ai API..."):
                    try:
                        live_client = VastAIClient(api_key=api_key_input)
                        live_host_df = live_client.fetch_hosts_offers([primary_host_id])
                        if not live_host_df.empty:
                            VastAIClient.record_raw_offers_snapshot(live_host_df)
                            if not host_hist_df.empty:
                                host_hist_df = pd.concat([host_hist_df, live_host_df], ignore_index=True).drop_duplicates(
                                    subset=["bundle_id", "snapshot_time"], keep="last"
                                )
                            else:
                                host_hist_df = live_host_df
                            st.toast(f"✅ Знайдено {len(live_host_df)} пропозицій для Host #{primary_host_id}!", icon="⚡")
                        else:
                            if host_hist_df.empty:
                                st.warning(f"⚠️ Vast.ai API не повернуло активних пропозицій для Host #{primary_host_id}.")
                    except Exception as e:
                        logger.warning(f"Host live fetch warning: {e}")

            fleet_metrics = VastAIClient.calculate_host_fleet_metrics(host_hist_df) if not host_hist_df.empty else {}

            if not fleet_metrics or fleet_metrics.get("total_machines", 0) == 0:
                st.warning(f"⚠️ Для Host ID #{primary_host_id} не знайдено машин на ринку Vast.ai або в базі даних. Перевірте правильність Host ID.")
            else:
                hm1, hm2, hm3, hm4 = st.columns(4)
                with hm1:
                    st.metric("🏢 Флот хостера", f"Host #{fleet_metrics['host_id']}", f"{fleet_metrics['total_machines']} машин ({fleet_metrics['total_gpus']} GPU)")
                with hm2:
                    rented_m = fleet_metrics["currently_rented_machines"]
                    total_m = fleet_metrics["total_machines"]
                    pct_active = (rented_m / total_m * 100.0) if total_m > 0 else 0.0
                    st.metric("🟢 В оренді зараз", f"{rented_m} / {total_m} машин", f"{pct_active:.0f}% активні")
                with hm3:
                    st.metric(f"📊 Сер. заповнення флоту ({host_days_back}д)", f"{fleet_metrics['avg_occupancy_pct']:.1f}%", "фактична зайнятість")
                with hm4:
                    st.metric(f"💰 Заробіток флоту ({host_days_back}д)", f"${fleet_metrics['total_fleet_earned_usd']:,.2f}", f"Прогноз: ~${fleet_metrics['projected_fleet_monthly_usd']:,.2f}/міс")

                st.caption(f"🎮 **Моделі GPU у флоті хостера:** {', '.join(fleet_metrics['gpu_models'])}")

                st.markdown(f"##### 📋 Всі машини хостера #{primary_host_id} ({len(fleet_metrics['machines_summary_df'])} серверів)")
                host_mach_order = render_column_order_selector("host_machines_table", list(fleet_metrics["machines_summary_df"].columns))
                st.dataframe(
                    fleet_metrics["machines_summary_df"],
                    column_order=host_mach_order,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Machine ID": st.column_config.NumberColumn("Machine ID", format="%d"),
                        "GPU Модель": "Модель GPU",
                        "GPU (шт)": st.column_config.NumberColumn("GPU (шт)", format="%d"),
                        "Поточний стан": st.column_config.TextColumn("Поточний стан", width="medium"),
                        "Ціна ($/год)": st.column_config.NumberColumn("Ціна машини ($/год)", format="$%.4f"),
                        "Ціна / 1 GPU ($/год)": st.column_config.NumberColumn("Ціна / 1 GPU ($/год)", format="$%.4f"),
                        "Заповнення (%)": st.column_config.ProgressColumn("Заповнення / Утилізація", min_value=0, max_value=100, format="%.1f%%"),
                        "Заробіток ($)": st.column_config.NumberColumn(f"Зароблено ({host_days_back}д)", format="$%.2f"),
                        "Прогноз ($/міс)": st.column_config.NumberColumn("Прогноз доходу ($/міс)", format="$%.2f"),
                        "Надійність (%)": st.column_config.NumberColumn("Надійність (%)", format="%.1f%%"),
                        "DLPerf": "DLPerf",
                        "Локація": "Локація",
                        "Останній зріз": "Останній зріз",
                    },
                )

                csv_fleet = fleet_metrics["machines_summary_df"].to_csv(index=False).encode("utf-8")
                st.download_button(
                    label=f"📥 Експорт списку машин Host #{primary_host_id} у CSV",
                    data=csv_fleet,
                    file_name=f"vast_host_{primary_host_id}_machines_{datetime.date.today()}.csv",
                    mime="text/csv",
                )

                st.markdown("---")
                st.markdown(f"##### 🔍 Детальний перегляд машини хостера #{primary_host_id}")
                host_m_options = [f"Machine #{row['Machine ID']} — {row['GPU Модель']} ({row['GPU (шт)']}x) | {row['Поточний стан']}" for _, row in fleet_metrics["machines_summary_df"].iterrows()]
                selected_hm_label = st.selectbox("Оберіть машину для перегляду графіків:", options=host_m_options, index=0)
                selected_hm_id = int(selected_hm_label.split()[1].replace("#", ""))

                hm_sub = host_hist_df[host_hist_df["machine_id"] == selected_hm_id]
                hm_metrics = VastAIClient.calculate_machine_detailed_metrics(hm_sub)

                if hm_metrics:
                    hchart1, hchart2 = st.columns([3, 2])
                    with hchart1:
                        price_fig = create_machine_price_timeline_chart(
                            timeline_df=hm_metrics["timeline_df"],
                            machine_id=hm_metrics["machine_id"],
                            gpu_name=hm_metrics["display_name"],
                        )
                        st.plotly_chart(price_fig, use_container_width=True)
                    with hchart2:
                        st.markdown("##### ⏱️ Розподіл зайнятості у часі")
                        state_fig = create_machine_occupancy_timeline_chart(
                            timeline_df=hm_metrics["timeline_df"],
                            machine_id=hm_metrics["machine_id"],
                        )
                        st.plotly_chart(state_fig, use_container_width=True)

        with st.expander(f"🌐 Каталог найбільших хостерів ринку в базі SQLite ({days_back} днів)", expanded=False):
            if all_hosts_db.empty:
                st.info("ℹ️ У базі даних ще немає записів про хостерів.")
            else:
                st.caption(f"Знайдено **{len(all_hosts_db):,}** унікальних хостерів, збережених у системі.")
                st.dataframe(
                    all_hosts_db[[
                        "host_id", "total_machines", "occupancy_pct", "avg_dph_total",
                        "avg_dph_per_gpu", "avg_reliability", "geolocation", "total_snapshots", "last_seen"
                    ]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "host_id": st.column_config.NumberColumn("Host ID", format="%d"),
                        "total_machines": st.column_config.NumberColumn("Машин у флоті (шт)", format="%d"),
                        "occupancy_pct": st.column_config.ProgressColumn("Заповнення флоту", min_value=0, max_value=100, format="%.1f%%"),
                        "avg_dph_total": st.column_config.NumberColumn("Сер. ціна сервера ($/год)", format="$%.4f"),
                        "avg_dph_per_gpu": st.column_config.NumberColumn("Сер. ціна / 1 GPU ($/год)", format="$%.4f"),
                        "avg_reliability": st.column_config.NumberColumn("Надійність (%)", format="%.1f%%"),
                        "geolocation": "Локація",
                        "total_snapshots": st.column_config.NumberColumn("Зрізів у БД", format="%d"),
                        "last_seen": "Останній зріз",
                    },
                )
    else:
        # Machine ID Mode
        st.markdown("##### 🖥️ Відстеження конкретних машин за Machine ID")
        m_col1, m_col2, m_col3 = st.columns([2.5, 1.5, 1])
        with m_col1:
            current_watched = st.session_state.get("watched_machine_ids", [55957, 29796])
            input_ids_str = st.text_input(
                "Введіть Machine ID (через кому або пробіл):",
                value=", ".join(str(m) for m in current_watched),
                placeholder="Наприклад: 55957, 29796, 140879, 148324",
                help="Вкажіть один або кілька Machine ID хостів для відстеження їхньої утилізації та ставок оренди.",
            )
        with m_col2:
            try:
                all_machines_db = VastAIClient.get_all_tracked_machines_summary(days_back=days_back)
            except Exception:
                all_machines_db = pd.DataFrame()
            quick_select_options = ["— Оберіть популярну машину з БД —"]
            if not all_machines_db.empty:
                for _, mrow in all_machines_db.head(25).iterrows():
                    quick_select_options.append(f"#{mrow['machine_id']} — {mrow['display_name']} ({mrow['num_gpus']}x) | Заповн: {mrow['occupancy_pct']}%")

            quick_picked = st.selectbox("Швидкий вибір із бази даних:", options=quick_select_options, index=0)
        with m_col3:
            mach_days_back = st.selectbox(
                "Період аналізу:",
                [1, 3, 7, 14, 30, 60],
                index=2,  # 7 days
                format_func=lambda d: f"{d} дн" if d != 1 else "24 год",
                help="Період, за який розраховується заповнення та заробіток",
            )

        # Parse entered machine IDs
        parsed_ids = []
        for token in input_ids_str.replace(";", ",").replace(" ", ",").split(","):
            token = token.strip()
            if token.isdigit():
                val = int(token)
                if val not in parsed_ids:
                    parsed_ids.append(val)

        if quick_picked != "— Оберіть популярну машину з БД —":
            try:
                picked_id = int(quick_picked.split()[0].replace("#", ""))
                if picked_id not in parsed_ids:
                    parsed_ids.append(picked_id)
            except Exception:
                pass

        if parsed_ids != current_watched:
            st.session_state["watched_machine_ids"] = parsed_ids
            save_preferences({"watched_machine_ids": parsed_ids})

        if not parsed_ids:
            st.info("ℹ️ Введіть Machine ID у поле вище або оберіть зі списку для відстеження.")
        else:
            col_m_act1, col_m_act2 = st.columns([1.8, 4])
            with col_m_act1:
                refresh_mach_btn = st.button("🔄 Оновити машини з Vast.ai API", key="refresh_mach_api_btn", use_container_width=True)

            # Load history for all tracked machines
            try:
                all_mach_hist = VastAIClient.get_machine_history(machine_ids=parsed_ids, days_back=mach_days_back)
            except Exception:
                all_mach_hist = pd.DataFrame()

            # Identify which machine IDs have no records or if user requested refresh
            existing_mids = set(all_mach_hist["machine_id"].unique()) if not all_mach_hist.empty else set()
            mids_to_fetch = parsed_ids if refresh_mach_btn else [mid for mid in parsed_ids if mid not in existing_mids]

            if mids_to_fetch:
                with st.spinner(f"⚡ Отримання даних з Vast.ai API для Machine ID: {', '.join(str(m) for m in mids_to_fetch)}..."):
                    try:
                        live_client = VastAIClient(api_key=api_key_input)
                        live_mach_df = live_client.fetch_machines_offers(mids_to_fetch)
                        if not live_mach_df.empty:
                            VastAIClient.record_raw_offers_snapshot(live_mach_df)
                            if not all_mach_hist.empty:
                                all_mach_hist = pd.concat([all_mach_hist, live_mach_df], ignore_index=True).drop_duplicates(
                                    subset=["bundle_id", "snapshot_time"], keep="last"
                                )
                            else:
                                all_mach_hist = live_mach_df
                            st.toast(f"✅ Знайдено {len(live_mach_df)} пропозицій для обраних машин!", icon="⚡")
                    except Exception as e:
                        logger.warning(f"Machine live fetch warning: {e}")

            # Build comparison summary list
            mach_summaries = []
            for mid in parsed_ids:
                m_sub = all_mach_hist[all_mach_hist["machine_id"] == mid] if not all_mach_hist.empty else pd.DataFrame()
                if not m_sub.empty:
                    m_metrics = VastAIClient.calculate_machine_detailed_metrics(m_sub)
                    mach_summaries.append(m_metrics)
                else:
                    mach_summaries.append({
                        "machine_id": mid,
                        "display_name": "Не знайдено на Vast.ai",
                        "num_gpus": 0,
                        "occupancy_pct": 0.0,
                        "latest_status": "⚪ Немає даних",
                        "latest_price_total": 0.0,
                        "latest_price_per_gpu": 0.0,
                        "total_earned_usd": 0.0,
                        "projected_monthly_usd": 0.0,
                        "reliability_pct": 0.0,
                        "geolocation": "—",
                        "latest_snapshot_time": None,
                        "total_snapshots": 0,
                    })

            if mach_summaries:
                valid_summaries = [m for m in mach_summaries if m.get("total_snapshots", 0) > 0]
                if valid_summaries:
                    total_watched = len(valid_summaries)
                    currently_rented = sum(1 for m in valid_summaries if m.get("is_rented_now", False))
                    avg_occ = float(np.mean([m.get("occupancy_pct", 0.0) for m in valid_summaries]))
                    total_period_earnings = sum(m.get("total_earned_usd", 0.0) for m in valid_summaries)

                    sm1, sm2, sm3, sm4 = st.columns(4)
                    with sm1:
                        st.metric("🖥️ Машин у моніторингу", f"{total_watched} шт")
                    with sm2:
                        st.metric("🟢 В оренді зараз", f"{currently_rented} / {total_watched} шт", f"{currently_rented / total_watched * 100:.0f}% активні")
                    with sm3:
                        st.metric(f"📊 Сер. заповнення ({mach_days_back}д)", f"{avg_occ:.1f}%", "фактична зайнятість")
                    with sm4:
                        st.metric(f"💰 Сумарний дохід ({mach_days_back}д)", f"${total_period_earnings:,.2f}", "накопичено машинами")

                # Comparison Overview Table
                st.markdown("##### 📋 Зведена таблиця відстежуваних машин")
                comp_table_rows = []
                for m in mach_summaries:
                    comp_table_rows.append({
                        "Machine ID": m["machine_id"],
                        "GPU Модель": m["display_name"],
                        "GPU (шт)": m["num_gpus"],
                        "Поточний стан": m["latest_status"],
                        "Ціна ($/год)": m["latest_price_total"],
                        "Ціна / 1 GPU ($/год)": m["latest_price_per_gpu"],
                        "Заповнення (%)": m["occupancy_pct"],
                        "Заробіток ($)": m["total_earned_usd"],
                        "Прогноз ($/міс)": m.get("projected_monthly_usd", 0.0),
                        "Надійність (%)": m.get("reliability_pct", 0.0),
                        "Локація": m.get("geolocation", "—"),
                        "Останній зріз": str(m.get("latest_snapshot_time") or "—"),
                    })
                comp_df = pd.DataFrame(comp_table_rows)

                mach_col_order = render_column_order_selector("machines_overview_table", list(comp_df.columns))
                st.dataframe(
                    comp_df,
                    column_order=mach_col_order,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Machine ID": st.column_config.NumberColumn("Machine ID", format="%d"),
                        "GPU Модель": "Модель GPU",
                        "GPU (шт)": st.column_config.NumberColumn("GPU (шт)", format="%d"),
                        "Поточний стан": st.column_config.TextColumn("Поточний стан", width="medium"),
                        "Ціна ($/год)": st.column_config.NumberColumn("Ціна машини ($/год)", format="$%.4f"),
                        "Ціна / 1 GPU ($/год)": st.column_config.NumberColumn("Ціна / 1 GPU ($/год)", format="$%.4f"),
                        "Заповнення (%)": st.column_config.ProgressColumn("Заповнення / Утилізація", min_value=0, max_value=100, format="%.1f%%"),
                        "Заробіток ($)": st.column_config.NumberColumn(f"Зароблено за {mach_days_back}д", format="$%.2f"),
                        "Прогноз ($/міс)": st.column_config.NumberColumn("Прогноз доходу ($/міс)", format="$%.2f"),
                        "Надійність (%)": st.column_config.NumberColumn("Надійність (%)", format="%.1f%%"),
                        "Локація": "Локація",
                        "Останній зріз": "Останній зріз",
                    },
                )

                # Deep-dive selection
                st.markdown("---")
                st.markdown("##### 🔍 Детальний аналіз конкретної машини (Deep Dive)")

                selectable_machines = [m for m in mach_summaries if m.get("total_snapshots", 0) > 0]
                if not selectable_machines:
                    st.warning("⚠️ За обраними Machine ID немає збереженої історії в базі. Натисніть «Оновити дані» або зачекайте автозбору.")
                else:
                    m_labels = [f"Machine #{m['machine_id']} — {m['display_name']} ({m['num_gpus']}x GPU) | Заповнення {m['occupancy_pct']}%" for m in selectable_machines]
                    selected_label = st.selectbox("Оберіть машину для детального перегляду графіків:", options=m_labels, index=0)
                    selected_mach_id = selectable_machines[m_labels.index(selected_label)]["machine_id"]
                    curr_mach_metrics = next(m for m in selectable_machines if m["machine_id"] == selected_mach_id)

                    # Metric cards for single machine
                    dm1, dm2, dm3, dm4 = st.columns(4)
                    with dm1:
                        st.metric(
                            "🟢 Поточний стан",
                            curr_mach_metrics["latest_status"],
                            f"Оновлено: {format_time_ago(curr_mach_metrics['latest_snapshot_time'])}"
                        )
                    with dm2:
                        st.metric(
                            "🏷️ Ставка оренди",
                            f"${curr_mach_metrics['latest_price_total']:.4f}/год",
                            f"${curr_mach_metrics['latest_price_per_gpu']:.4f}/год на 1 GPU"
                        )
                    with dm3:
                        st.metric(
                            f"📊 Заповнення ({mach_days_back} днів)",
                            f"{curr_mach_metrics['occupancy_pct']:.1f}%",
                            f"{curr_mach_metrics['rented_snapshots']} з {curr_mach_metrics['total_snapshots']} зрізів в оренді"
                        )
                    with dm4:
                        st.metric(
                            f"💵 Заробіток за {mach_days_back} днів",
                            f"${curr_mach_metrics['total_earned_usd']:.2f}",
                            f"Прогноз: ~${curr_mach_metrics['projected_monthly_usd']:.2f} / міс"
                        )

                    # Hardware & Connection info row
                    spec_col1, spec_col2, spec_col3, spec_col4 = st.columns(4)
                    with spec_col1:
                        st.caption(f"📍 **Локація:** {curr_mach_metrics['geolocation']}")
                    with spec_col2:
                        st.caption(f"🛡️ **Надійність:** {curr_mach_metrics['reliability_pct']}%")
                    with spec_col3:
                        st.caption(f"🏎️ **DLPerf:** {curr_mach_metrics['dlperf']}")
                    with spec_col4:
                        st.caption(f"🌐 **Швидкість мережі:** ↓{curr_mach_metrics['inet_down_mbps']} / ↑{curr_mach_metrics['inet_up_mbps']} Mbps")

                    # Charts
                    mchart_col1, mchart_col2 = st.columns([3, 2])
                    with mchart_col1:
                        price_fig = create_machine_price_timeline_chart(
                            timeline_df=curr_mach_metrics["timeline_df"],
                            machine_id=curr_mach_metrics["machine_id"],
                            gpu_name=curr_mach_metrics["display_name"],
                        )
                        st.plotly_chart(price_fig, use_container_width=True)

                    with mchart_col2:
                        st.markdown("##### ⏱️ Розподіл зайнятості у часі")
                        state_fig = create_machine_occupancy_timeline_chart(
                            timeline_df=curr_mach_metrics["timeline_df"],
                            machine_id=curr_mach_metrics["machine_id"],
                        )
                        st.plotly_chart(state_fig, use_container_width=True)

                        # Price stats breakdown
                        st.markdown("##### 🏷️ Статистика цін машини за період")
                        p_stat1, p_stat2, p_stat3 = st.columns(3)
                        with p_stat1:
                            st.caption(f"• **Мін. ціна:** ${curr_mach_metrics['min_price_total']:.4f}/год")
                        with p_stat2:
                            st.caption(f"• **Медіана:** ${curr_mach_metrics['median_price_total']:.4f}/год")
                        with p_stat3:
                            st.caption(f"• **Макс. ціна:** ${curr_mach_metrics['max_price_total']:.4f}/год")

                    # Market Benchmark
                    if not hist_summary_df.empty:
                        gpu_bench = hist_summary_df[hist_summary_df["Карта"] == curr_mach_metrics["display_name"]]
                        if not gpu_bench.empty:
                            bench_row = gpu_bench.iloc[0]
                            market_median = float(bench_row["Медіана ($/год)"])
                            market_util = float(bench_row["Утилізація (%)"])

                            mach_unit_price = curr_mach_metrics["latest_price_per_gpu"]
                            price_diff_pct = ((mach_unit_price - market_median) / market_median * 100.0) if market_median > 0 else 0.0
                            diff_sign = "+" if price_diff_pct > 0 else ""

                            st.info(
                                f"📊 **Порівняння з ринком Vast.ai ({curr_mach_metrics['display_name']}):** "
                                f"Ваша ставка **${mach_unit_price:.4f}/год на 1 GPU** є на **{diff_sign}{price_diff_pct:.1f}%** "
                                f"від медіани ринку (**${market_median:.4f}/год**). "
                                f"Заповнення цієї машини: **{curr_mach_metrics['occupancy_pct']:.1f}%** "
                                f"(середнє по ринку для цієї моделі: **{market_util:.1f}%**)."
                            )

                    # History table for single machine
                    with st.expander(f"📋 Детальна історія всіх {len(curr_mach_metrics['timeline_df'])} зрізів для Machine #{selected_mach_id}", expanded=False):
                        m_table_df = curr_mach_metrics["timeline_df"][[
                            "snapshot_time", "display_name", "num_gpus", "dph_total", "dph_per_gpu", "status_label",
                            "reliability_pct", "dlperf", "inet_down_mbps", "inet_up_mbps", "geolocation"
                        ]].sort_values(by="snapshot_time", ascending=False)

                        st.dataframe(
                            m_table_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "snapshot_time": "Час зрізу",
                                "display_name": "Модель GPU",
                                "num_gpus": "GPU (шт)",
                                "dph_total": st.column_config.NumberColumn("Ціна машини ($/год)", format="$%.4f"),
                                "dph_per_gpu": st.column_config.NumberColumn("Ціна / 1 GPU ($/год)", format="$%.4f"),
                                "status_label": "Статус",
                                "reliability_pct": st.column_config.NumberColumn("Надійність (%)", format="%.1f%%"),
                                "dlperf": "DLPerf",
                                "inet_down_mbps": "Down (Mbps)",
                                "inet_up_mbps": "Up (Mbps)",
                                "geolocation": "Локація",
                            },
                        )

                        csv_m = m_table_df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label=f"📥 Експорт історії Machine #{selected_mach_id} у CSV",
                            data=csv_m,
                            file_name=f"vast_machine_{selected_mach_id}_history_{datetime.date.today()}.csv",
                            mime="text/csv",
                        )

        # Explorer section for all machines
        with st.expander(f"🌐 Каталог усіх активних машин у базі даних SQLite ({days_back} днів)", expanded=False):
            if all_machines_db.empty:
                st.info("ℹ️ У базі даних ще немає записів про машини.")
            else:
                st.caption(f"Знайдено **{len(all_machines_db):,}** унікальних машин, збережених у системі. Використовуйте Machine ID для відстеження.")
                st.dataframe(
                    all_machines_db[[
                        "machine_id", "display_name", "num_gpus", "occupancy_pct", "avg_dph_total",
                        "avg_dph_per_gpu", "avg_reliability", "geolocation", "total_snapshots", "last_seen"
                    ]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "machine_id": st.column_config.NumberColumn("Machine ID", format="%d"),
                        "display_name": "Модель GPU",
                        "num_gpus": "GPU (шт)",
                        "occupancy_pct": st.column_config.ProgressColumn("Заповнення / Утилізація", min_value=0, max_value=100, format="%.1f%%"),
                        "avg_dph_total": st.column_config.NumberColumn("Сер. ціна машини ($/год)", format="$%.4f"),
                        "avg_dph_per_gpu": st.column_config.NumberColumn("Сер. ціна / 1 GPU ($/год)", format="$%.4f"),
                        "avg_reliability": st.column_config.NumberColumn("Надійність (%)", format="%.1f%%"),
                        "geolocation": "Локація",
                        "total_snapshots": st.column_config.NumberColumn("Зрізів у БД", format="%d"),
                        "last_seen": "Останній зріз",
                    },
                )



with tab_summary:
    st.markdown("#### 📋 Зведена статистика ринку GPU на Vast.ai")
    
    summary_view = st.radio(
        "Режим перегляду зведення:",
        ["⚡ Поточний Live-зріз", f"📈 Історичне зведення ({days_back} днів)"],
        horizontal=True,
    )

    if "Історичне" in summary_view:
        active_summary_df = VastAIClient.get_historical_summary(
            selected_gpus=selected_gpus if selected_gpus else None,
            price_mode=price_mode,
            days_back=days_back,
            live_summary_df=summary_df,
        )
    else:
        active_summary_df = summary_df

    summary_col_order = render_column_order_selector("summary_table", list(active_summary_df.columns))
    st.dataframe(
        active_summary_df,
        column_order=summary_col_order,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Карта": st.column_config.TextColumn("Модель GPU", width="medium"),
            "Мін. ціна ($/год)": st.column_config.NumberColumn(format="$%.4f"),
            "Сер. ціна ($/год)": st.column_config.NumberColumn(format="$%.4f"),
            "Медіана ($/год)": st.column_config.NumberColumn(format="$%.4f"),
            "P10 ($/год)": st.column_config.NumberColumn(format="$%.4f"),
            "P90 ($/год)": st.column_config.NumberColumn(format="$%.4f"),
            "Макс. ціна ($/год)": st.column_config.NumberColumn(format="$%.4f"),
            "Утилізація (%)": st.column_config.ProgressColumn("Утилізація", min_value=0, max_value=100, format="%.1f%%"),
            "Мін. утилізація (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "Макс. утилізація (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "Доступно (шт)": st.column_config.NumberColumn(format="%d"),
            "Всього серверів (шт)": st.column_config.NumberColumn(format="%d"),
            "К-сть вимірів": st.column_config.NumberColumn(format="%d"),
        },
    )


    csv_summary = active_summary_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Експорт зведеної статистики у CSV",
        data=csv_summary,
        file_name=f"vast_gpu_summary_{datetime.date.today()}.csv",
        mime="text/csv",
        use_container_width=True,
    )


with tab_offers:
    st.markdown("#### 🔍 Усі активні пропозиції ринку (деталізовано)")
    display_cols = [
        "machine_id", "display_name", "num_gpus", "gpu_ram_gb", "dph_per_gpu", "dph_total",
        "rentable", "reliability_pct", "dlperf", "inet_down_mbps", "inet_up_mbps", "geolocation"
    ]
    offers_col_order = render_column_order_selector("live_offers_table", display_cols)
    st.dataframe(
        filtered_df[display_cols],
        column_order=offers_col_order,
        use_container_width=True,
        hide_index=True,
        column_config={
            "machine_id": st.column_config.NumberColumn("Machine ID", format="%d"),
            "display_name": "Модель GPU",
            "num_gpus": "К-сть GPU",
            "gpu_ram_gb": "VRAM (GB)",
            "dph_per_gpu": st.column_config.NumberColumn("Ціна / 1 GPU ($/год)", format="$%.4f"),
            "dph_total": st.column_config.NumberColumn("Ціна сервера ($/год)", format="$%.4f"),
            "rentable": "Доступний зараз",
            "reliability_pct": st.column_config.NumberColumn("Надійність (%)", format="%.1f%%"),
            "dlperf": "DLPerf",
            "inet_down_mbps": "Down (Mbps)",
            "inet_up_mbps": "Up (Mbps)",
            "geolocation": "Локація",
        },
    )

    csv_raw = filtered_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Експорт поточного зрізу пропозицій у CSV",
        data=csv_raw,
        file_name=f"vast_gpu_offers_raw_{datetime.date.today()}.csv",
        mime="text/csv",
    )

with tab_history:
    st.markdown("#### 💾 Історичний датасет ринку (накопичений у SQLite)")
    raw_hist_df = VastAIClient.get_raw_dataset_history(
        selected_gpus=selected_gpus if selected_gpus else None,
        days_back=days_back,
    )

    if raw_hist_df.empty and 'raw_df' in locals() and not raw_df.empty:
        VastAIClient.record_raw_offers_snapshot(raw_df)
        raw_hist_df = VastAIClient.get_raw_dataset_history(
            selected_gpus=selected_gpus if selected_gpus else None,
            days_back=days_back,
        )

    if raw_hist_df.empty:
        st.info("ℹ️ У базі даних ще немає збережених записів за обраний період. Зачекайте автооновлення або натисніть «Записати зріз у БД зараз» у боковій панелі.")
    else:
        st.success(f"📦 Знайдено **{len(raw_hist_df):,}** історичних записів серверів за останні {days_back} днів.")
        hist_display_cols = [
            "snapshot_time", "machine_id", "display_name", "num_gpus", "gpu_ram_gb", "dph_per_gpu",
            "dph_total", "rentable", "reliability_pct", "dlperf", "inet_down_mbps", "geolocation"
        ]
        history_col_order = render_column_order_selector("history_dataset_table", hist_display_cols)
        st.dataframe(
            raw_hist_df[hist_display_cols],
            column_order=history_col_order,
            use_container_width=True,
            hide_index=True,
            column_config={
                "snapshot_time": "Час зрізу",
                "machine_id": st.column_config.NumberColumn("Machine ID", format="%d"),
                "display_name": "Модель GPU",
                "num_gpus": "К-сть GPU",
                "gpu_ram_gb": "VRAM (GB)",
                "dph_per_gpu": st.column_config.NumberColumn("Ціна / 1 GPU ($/год)", format="$%.4f"),
                "dph_total": st.column_config.NumberColumn("Ціна сервера ($/год)", format="$%.4f"),
                "rentable": "Доступний",
                "reliability_pct": st.column_config.NumberColumn("Надійність (%)", format="%.1f%%"),
                "dlperf": "DLPerf",
                "inet_down_mbps": "Down (Mbps)",
                "geolocation": "Локація",
            },
        )

        csv_history = raw_hist_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Експорт повного історичного датасету з SQLite у CSV",
            data=csv_history,
            file_name=f"vast_gpu_historical_dataset_{datetime.date.today()}.csv",
            mime="text/csv",
            use_container_width=True,
        )


