import json

import streamlit as st

import page_watcher

st.set_page_config(page_title="Price Watch", page_icon="\U0001F4B0", layout="wide")
st.title("Price Watch")
st.caption(
    "Watches a product page for price changes and pings Telegram when the "
    "price moves past your threshold in either direction. Checked on a slower "
    "schedule than the other watchers (default every 4 hours) since hammering "
    "a site like Amazon too often risks getting blocked."
)

INTERVAL_OPTIONS = {
    "Every hour": 60,
    "Every 4 hours": 240,
    "Every 12 hours": 720,
    "Once a day": 1440,
}


def _load_pages():
    return page_watcher._load_config().get("pages", [])


def _save_pages(pages):
    config = page_watcher._load_config()
    config["pages"] = pages
    page_watcher.CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


st.subheader("Add a page to watch")
with st.form("add_price_watch", clear_on_submit=True):
    name = st.text_input("Name", placeholder="e.g. GUNNER Training Bumper")
    url = st.text_input("Product URL")
    col1, col2 = st.columns(2)
    with col1:
        threshold = st.number_input(
            "Notify when price moves by at least (%)", min_value=1.0, max_value=100.0, value=10.0, step=1.0
        )
    with col2:
        interval_label = st.selectbox("Check frequency", list(INTERVAL_OPTIONS.keys()), index=1)
    with st.expander("Advanced: CSS selector (only needed if auto-detection picks the wrong price)"):
        css_selector = st.text_input(
            "CSS selector",
            placeholder="e.g. #corePriceDisplay_desktop_feature_div",
            help="Leave blank to auto-detect. Amazon product pages are auto-detected out of the box.",
        )
    submitted = st.form_submit_button("Add and check now")

if submitted:
    if not name or not url:
        st.error("Name and URL are both required.")
    elif any(p["name"] == name for p in _load_pages()):
        st.error(f"A watched page named '{name}' already exists — pick a different name.")
    else:
        state = page_watcher._load_state()
        with st.spinner(f"Fetching {url} ..."):
            result = page_watcher._check_price_page(
                name, url, css_selector or None, threshold, INTERVAL_OPTIONS[interval_label], state
            )
        if name not in state:
            st.error(f"Couldn't add this page: {result}")
        else:
            pages = _load_pages()
            pages.append({
                "name": name,
                "url": url,
                "price_threshold_pct": threshold,
                "check_interval_minutes": INTERVAL_OPTIONS[interval_label],
                **({"css_selector": css_selector} if css_selector else {}),
            })
            _save_pages(pages)
            page_watcher._save_state(state)
            st.success(f"Added — {result}")
            st.rerun()

st.divider()
st.subheader("Currently watched")

pages = _load_pages()
price_pages = [p for p in pages if p.get("price_threshold_pct") is not None]

if not price_pages:
    st.caption("No price watches yet — add one above.")
else:
    state = page_watcher._load_state()
    for page in price_pages:
        entry = state.get(page["name"], {})
        with st.container(border=True):
            header_col, remove_col = st.columns([5, 1])
            with header_col:
                st.markdown(f"**[{page['name']}]({page['url']})**")
            with remove_col:
                if st.button("Remove", key=f"remove_{page['name']}"):
                    _save_pages([p for p in pages if p["name"] != page["name"]])
                    state.pop(page["name"], None)
                    page_watcher._save_state(state)
                    st.rerun()

            cols = st.columns(4)
            reference_price = entry.get("reference_price")
            last_price = entry.get("last_price")
            cols[0].metric("Current price", f"${last_price:.2f}" if last_price is not None else "—")
            if reference_price is not None and last_price is not None and reference_price:
                pct = (last_price - reference_price) / reference_price * 100
                cols[1].metric("Since reference", f"${reference_price:.2f}", delta=f"{pct:+.1f}%")
            else:
                cols[1].metric("Reference price", "—")
            cols[2].metric("Threshold", f"±{page['price_threshold_pct']:.0f}%")
            interval_minutes = page.get("check_interval_minutes", page_watcher.DEFAULT_PRICE_CHECK_INTERVAL_MINUTES)
            label = next((k for k, v in INTERVAL_OPTIONS.items() if v == interval_minutes), f"Every {interval_minutes} min")
            cols[3].metric("Frequency", label)

            checked_at = entry.get("last_checked_at")
            st.caption(f"Last checked: {checked_at or 'never'}")

            if st.button("Check now", key=f"check_{page['name']}"):
                with st.spinner("Checking..."):
                    result = page_watcher._check_price_page(
                        page["name"], page["url"], page.get("css_selector"),
                        page["price_threshold_pct"], 0, state,
                    )
                page_watcher._save_state(state)
                st.info(result)
                st.rerun()
