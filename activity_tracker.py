import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_oauth import OAuth2Component, StreamlitOauthError
from datetime import datetime, timedelta, date
from uuid import uuid4
import requests

st.set_page_config(page_title="🚦 Multi-Tenant Maintenance Activity Tracker", layout="wide")

# ---- Google Sheets API Setup ----
def get_gsheet_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    if "google_credentials" in st.secrets:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["google_credentials"], scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    return gspread.authorize(creds)

client = get_gsheet_client()

def read_df(sheet_url, sheet_name="Sheet1"):
    sheet = client.open_by_url(sheet_url)
    data = sheet.worksheet(sheet_name).get_all_records()
    return pd.DataFrame(data)

def write_df(sheet_url, df, sheet_name="Sheet1"):
    sheet = client.open_by_url(sheet_url)
    ws = sheet.worksheet(sheet_name)
    ws.clear()
    if not df.empty:
        df = df.astype(str)
        ws.update([df.columns.values.tolist()] + df.values.tolist())

# ---- Helper: Load/save users and societies from Sheets ----
USERS_URL = st.secrets["sheets"]["users_url"]
SOCIETIES_URL = st.secrets["sheets"]["societies_url"]

def read_users():
    df = read_df(USERS_URL)
    if not df.empty:
        df = df.drop_duplicates(subset=["email"])
        return df.to_dict(orient="records")
    return []

def save_users(users):
    df = pd.DataFrame(users)
    write_df(USERS_URL, df)

def read_societies():
    df = read_df(SOCIETIES_URL)
    if not df.empty:
        df = df.drop_duplicates(subset=["name"])
        return df.to_dict(orient="records")
    return []

def save_societies(societies):
    df = pd.DataFrame(societies)
    write_df(SOCIETIES_URL, df)

users = read_users()
societies = read_societies()

# ---- Google OAuth2 Setup ----
CLIENT_ID = st.secrets["google"].get("client_id", "")
CLIENT_SECRET = st.secrets["google"].get("client_secret", "")
REDIRECT_URI = st.secrets["google"].get("redirect_uri", "")

if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
    st.error("Missing Google OAuth credentials! Check your Streamlit secrets configuration.")
    st.stop()

oauth2 = OAuth2Component(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
)

# --- Google Login Button with error handling ---
try:
    result = oauth2.authorize_button(
        name="Continue with Google",
        redirect_uri=REDIRECT_URI,
        scope="openid email profile",
        key="google",
    )
except StreamlitOauthError:
    st.warning("Authentication failed or session expired. Please refresh the page and try logging in again.")
    st.stop()

if result and "token" in result:
    # Get user info from Google
    access_token = result["token"]["access_token"]
    resp = requests.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={
        "Authorization": f"Bearer {access_token}"
    })
    user_info = resp.json()
    user_email = user_info["email"].lower()

    # Map user to role and society
    user_record = next((u for u in users if u["email"].lower() == user_email), None)
    if not user_record:
        st.error("You are not authorized to access this application.")
        st.stop()

    role = user_record["role"]

    # ---- Sidebar (safe: only after login!) ----
    st.sidebar.write(f"Logged in as: {user_email} ({role.replace('_', ' ').title()})")

    # --- Society selection, safely in session_state ---
    if role == "top_admin":
        allowed_societies = [s["name"] for s in societies]
        if "selected_society" not in st.session_state or st.session_state["selected_society"] not in allowed_societies:
            st.session_state["selected_society"] = allowed_societies[0]
        selected_society = st.sidebar.selectbox(
            "Select Society",
            allowed_societies,
            index=allowed_societies.index(st.session_state["selected_society"]),
            key="selected_society"
        )
    else:
        selected_society = user_record["society"]
        st.sidebar.write(f"Society: {selected_society}")

    society = next(s for s in societies if s["name"] == selected_society)
    ACTIVITIES_URL = society["activities_url"]
    LOGS_URL = society["logs_url"]

    if "logo_url" in society and society["logo_url"]:
        st.sidebar.image(society["logo_url"], use_container_width=True)
    st.sidebar.write(f"**Current Society:** {selected_society}")

    # ---- Activity and Log Sheet Functions (per society) ----
    def load_activities():
        df = read_df(ACTIVITIES_URL)
        if not df.empty:
            if "ID" not in df.columns:
                df["ID"] = [str(uuid4()) for _ in range(len(df))]
            else:
                df["ID"] = df["ID"].apply(lambda x: str(uuid4()) if pd.isna(x) or str(x).strip() == "" else str(x))
            df["Recurrence"] = df["Recurrence"].apply(
                lambda x: eval(x) if isinstance(x, str) and x.startswith("{") else {"type": df["Schedule"] if "Schedule" in df else "daily"}
            )
            df["Tags"] = df.get("Tags", "").apply(lambda x: x.split(",") if isinstance(x, str) else [])
            df["Dependencies"] = df.get("Dependencies", "").apply(lambda x: x.split(",") if isinstance(x, str) else [])
        return df

    def save_activities(df):
        df_to_save = df.copy()
        df_to_save["Recurrence"] = df_to_save["Recurrence"].astype(str)
        df_to_save["Tags"] = df_to_save["Tags"].apply(lambda l: ",".join(l) if isinstance(l, list) else l)
        df_to_save["Dependencies"] = df_to_save["Dependencies"].apply(lambda l: ",".join(l) if isinstance(l, list) else l)
        for col in df_to_save.columns:
            df_to_save[col] = df_to_save[col].astype(str)
        write_df(ACTIVITIES_URL, df_to_save)

    def load_logs():
        df = read_df(LOGS_URL)
        if not df.empty and "Date" in df:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.dropna(subset=["Date"])
        return df

    def save_logs(df):
        df_to_save = df.copy()
        df_to_save["Date"] = df_to_save["Date"].astype(str)
        for col in df_to_save.columns:
            df_to_save[col] = df_to_save[col].astype(str)
        write_df(LOGS_URL, df_to_save)

    # ---- Utilities ----
    def get_today():
        return date.today()

    def recurrence_matches_today(rec, today):
        if not rec: return False
        t = rec.get("type", "daily")
        if t == "daily": return True
        elif t == "weekly": return today.weekday() in rec.get("days", [])
        elif t == "monthly": return today.day in rec.get("days", [1])
        elif t == "custom": return today.weekday() in rec.get("days", [])
        return False

    def can_mark_complete(act, activities, logs):
        for dep in act["Dependencies"]:
            dep_row = activities[activities["Activity"] == dep]
            if not dep_row.empty:
                dep_id = dep_row.iloc[0]["ID"]
                today = get_today()
                done_today = not logs[(logs["ActivityID"]==dep_id) & (logs["Date"]==pd.Timestamp(today))].empty
                if not done_today:
                    return False
        return True

    def is_overdue(act_id, logs, today):
        if "ActivityID" not in logs.columns:
            return False
        records = logs[(logs["ActivityID"] == act_id)]
        if not records.empty:
            last_done = records["Date"].max()
            return last_done.date() < today
        return True

    # --- TAB LAYOUT ---
    if role == "top_admin":
        dashboard_tab, admin_tab = st.tabs(["Dashboard", "Admin Console"])
    else:
        dashboard_tab, = st.tabs(["Dashboard"])

    with dashboard_tab:
        st.title(f"🚦 Maintenance Activity Tracker App for {selected_society}")

        activities = load_activities()
        logs = load_logs()
        today = get_today()

        # --- Sidebar Filters ---
        st.sidebar.header("🔎 Filter & Search")
        schedule_types = ["all", "daily", "weekly", "monthly", "custom"]
        selected_schedule = st.sidebar.selectbox("Show schedule type", schedule_types, index=0)
        search_term = st.sidebar.text_input("Search Activities")
        show_overdue = st.sidebar.checkbox("Show only overdue", value=False)
        history_rows = st.sidebar.slider("Show up to N history records/activity", min_value=5, max_value=50, value=10)

        def matches_filters(act):
            schedule_match = selected_schedule == "all" or act["Schedule"] == selected_schedule
            search_match = (search_term == "") or (search_term.lower() in act["Activity"].lower()) or (search_term.lower() in str(act.get("Description", "")).lower())
            return schedule_match and search_match

        filtered_activities = activities[activities.apply(matches_filters, axis=1)] if not activities.empty else activities

        # --- Role-Based Permissions ---
        can_manage_activities = (role == "top_admin") or (role == "society_admin")
        can_only_update = (role == "user")

        # --- Add/Edit/Delete Activities Section (Admins only) ---
        if can_manage_activities:
            with st.expander("➕ Add / ✏️ Edit / 🗑️ Delete Activities", expanded=len(activities)==0):
                mode = st.selectbox("Choose Action", ["Add", "Edit", "Delete"])
                if mode == "Add":
                    with st.form("add_form"):
                        name = st.text_input("Activity Name")
                        desc = st.text_area("Description")
                        tags = st.text_input("Tags (comma separated)").split(",")
                        schedule_type = st.selectbox("Schedule Type", ["daily", "weekly", "monthly", "custom"])
                        if schedule_type in ("custom", "weekly"):
                            rec_days = st.multiselect("Repeat on days", [0,1,2,3,4,5,6], format_func=lambda x: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][x])
                        elif schedule_type == "monthly":
                            rec_days = st.multiselect("Repeat on dates", list(range(1,29)))
                        else:
                            rec_days = []
                        recurrence = {"type": schedule_type, "days": rec_days} if rec_days else {"type": schedule_type}
                        dep_names = st.multiselect(
                            "Dependencies (must complete first)",
                            list(activities["Activity"]) if not activities.empty else []
                        )
                        submit = st.form_submit_button("Add Activity")
                        if submit and name:
                            try:
                                new_id = str(uuid4())
                                new_row = pd.DataFrame([{
                                    "Activity": name,
                                    "Description": desc,
                                    "Schedule": schedule_type,
                                    "Recurrence": recurrence,
                                    "Tags": [t.strip() for t in tags if t.strip()],
                                    "Dependencies": dep_names,
                                    "ID": new_id
                                }])
                                activities = pd.concat([activities, new_row], ignore_index=True)
                                save_activities(activities)
                                st.success(f"Activity '{name}' added! Please refresh the page.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error adding activity: {e}")

                elif mode == "Edit" and not activities.empty:
                    edit_id = st.selectbox(
                        "Select Activity",
                        activities["ID"],
                        format_func=lambda id: activities[activities["ID"] == id]["Activity"].values[0]
                    )
                    act_row = activities[activities["ID"] == edit_id].iloc[0]
                    with st.form("edit_form"):
                        name = st.text_input("Activity Name", value=act_row["Activity"])
                        desc = st.text_area("Description", value=act_row.get("Description", ""))
                        tags = st.text_input("Tags (comma separated)", value=",".join(act_row.get("Tags", []))).split(",")
                        dependency_options = list(activities[activities["ID"] != edit_id]["Activity"])
                        current_dependencies = [d for d in act_row.get("Dependencies", []) if d in dependency_options]
                        dep_names = st.multiselect(
                            "Dependencies (must complete first)",
                            dependency_options,
                            default=current_dependencies
                        )
                        submit = st.form_submit_button("Save Changes")
                        if submit:
                            try:
                                idx = activities[activities["ID"] == edit_id].index[0]
                                activities.at[idx, "Activity"] = name
                                activities.at[idx, "Description"] = desc
                                activities.at[idx, "Tags"] = [t.strip() for t in tags if t.strip()]
                                activities.at[idx, "Dependencies"] = dep_names
                                save_activities(activities)
                                st.success("Activity updated. Please refresh the page.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error updating activity: {e}")

                elif mode == "Delete" and not activities.empty:
                    del_id = st.selectbox(
                        "Select Activity",
                        activities["ID"],
                        format_func=lambda id: activities[activities["ID"] == id]["Activity"].values[0]
                    )
                    if st.button("Delete Activity"):
                        try:
                            activities = activities[activities["ID"] != del_id].reset_index(drop=True)
                            save_activities(activities)
                            st.warning("Activity deleted. Please refresh the page.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting activity: {e}")

        elif can_only_update:
            st.info("You can view and complete activities but cannot add/edit/delete them.")

        # --- Calendar View ---
        with st.expander("📅 Calendar View"):
            calendar_days = [today - timedelta(days=i) for i in range(30)][::-1]
            calendar_df = pd.DataFrame({"Date": calendar_days})
            for _, act in filtered_activities.iterrows():
                act_id = act["ID"]
                if not logs.empty and "Date" in logs.columns and "ActivityID" in logs.columns:
                    completed_days = set(logs[logs["ActivityID"] == act_id]["Date"].dt.date)
                else:
                    completed_days = set()
                calendar_df[act["Activity"]] = calendar_df["Date"].apply(lambda d: "✅" if d in completed_days else "❌")
            st.dataframe(calendar_df.set_index("Date"), use_container_width=True)

        # --- Activities Table with Quick Status & Comments ---
        st.header("Today's & Overdue Activities")
        for _, act in filtered_activities.iterrows():
            overdue = is_overdue(act["ID"], logs, today)
            if show_overdue and not overdue:
                continue
            if not recurrence_matches_today(act["Recurrence"], today) and not overdue:
                continue
            dep_met = can_mark_complete(act, activities, logs)
            c1, c2, c3 = st.columns([1,5,3])
            with c1:
                st.write("")
            with c2:
                st.markdown(f"**{act['Activity']}**")
                st.caption(act.get("Description",""))
                st.markdown(f"Tags: {' '.join(['#'+t for t in act.get('Tags',[])])}")
                if overdue:
                    st.markdown("**:red[Overdue!]**")
                if act.get("Dependencies"):
                    st.markdown(f"Depends on: {', '.join(act['Dependencies'])}")
                done_today = (
                    not logs.empty
                    and "ActivityID" in logs.columns
                    and "Date" in logs.columns
                    and not logs[(logs["ActivityID"]==act["ID"]) & (logs["Date"]==pd.Timestamp(today))].empty
                )
                if done_today:
                    st.success("Done Today")
                elif dep_met:
                    with st.form(f"form_{act['ID']}"):
                        comment = st.text_input(f"Comment", key=f"comment_{act['ID']}")
                        evidence = st.text_input("Evidence Link (URL or photo)")
                        submit = st.form_submit_button("Mark Complete")
                        if submit:
                            try:
                                missed_dates = []
                                if overdue:
                                    past = logs[logs["ActivityID"]==act["ID"]]
                                    if not past.empty:
                                        last_completed = past["Date"].max().date()
                                        missed_dates = [last_completed + timedelta(days=i) for i in range(1, (today - last_completed).days)]
                                new_entries = []
                                for d in missed_dates+[today]:
                                    new_entries.append({
                                        'Date': d, 'ActivityID': act['ID'], 'Status': 'Completed',
                                        'Evidence Link': evidence, 'Comments': comment,
                                        'User': user_email, 'Timestamp': datetime.now(), 'Overdue': d != today
                                    })
                                logs = pd.concat([logs, pd.DataFrame(new_entries)], ignore_index=True)
                                logs["Date"] = pd.to_datetime(logs["Date"], errors="coerce")
                                logs = logs.dropna(subset=["Date"])
                                save_logs(logs)
                                st.success("Marked complete with missed roll-over.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error logging activity completion: {e}")
                else:
                    st.warning("Dependencies not completed today.")

            with c3:
                if not logs.empty and "ActivityID" in logs.columns:
                    recent_log = logs[logs["ActivityID"] == act["ID"]].sort_values(by="Date", ascending=False).head(history_rows)
                    if not recent_log.empty:
                        st.write("Recent History:")
                        st.dataframe(recent_log[["Date", "Status", "Evidence Link", "Comments"]], use_container_width=True, hide_index=True)
                    else:
                        st.caption("No history for this activity.")
                else:
                    st.caption("No history for this activity.")

        # --- Analytics Dashboard ---
        with st.expander("📊 Analytics Dashboard"):
            st.markdown("**Completion Trends (last 30 days)**")
            if not logs.empty and "Date" in logs.columns and "ActivityID" in logs.columns:
                df = logs[logs["Date"] >= (datetime.now()-timedelta(days=30))]
                if not df.empty:
                    summary = df.groupby('ActivityID').agg(Count=('Status','count')).reset_index()
                    summary['Activity'] = summary['ActivityID'].map({row['ID']:row['Activity'] for _,row in activities.iterrows()})
                    st.bar_chart(summary.set_index('Activity')['Count'])
                else:
                    st.info("No completion data yet.")
            else:
                st.info("No completion data yet or 'Date'/'ActivityID' column missing in logs.")

        # --- Export/Import Data ---
        with st.expander("⬇️⬆️ Export/Import Data"):
            st.download_button("Export Activities CSV", data=activities.to_csv(index=False), file_name="activities.csv")
            st.download_button("Export Log CSV", data=logs.to_csv(index=False), file_name="activity_log.csv")

        # --- Dependencies Matrix ---
        with st.expander("📦 Activity Dependencies"):
            dep_data = []
            for _, act in activities.iterrows():
                for dep in act.get("Dependencies", []):
                    dep_data.append({"Activity": act["Activity"], "Depends On": dep})
            if dep_data:
                st.dataframe(pd.DataFrame(dep_data))
            else:
                st.info("No dependencies set.")

    # --- ADMIN TAB (All uses Google Sheets for persistence!) ---
    if role == "top_admin":
        with admin_tab:
            st.header("🔑 Admin Console: Manage Users and Societies")

            # --- USERS TABLE ---
            users = read_users()  # Reload to get updates
            users_df = pd.DataFrame(users)
            st.subheader("👥 Users Management")
            st.dataframe(users_df[["email", "role", "society"]], use_container_width=True)

            st.markdown("### Add or Edit User")
            with st.form("add_edit_user"):
                new_email = st.text_input("Email", "")
                new_role = st.selectbox("Role", ["top_admin", "society_admin", "user"])
                society_options = [s["name"] for s in societies] + (["all"] if new_role == "top_admin" else [])
                new_society = st.selectbox("Society", society_options)
                submit_user = st.form_submit_button("Add / Update User")
                if submit_user and new_email:
                    users = read_users()  # Always reload
                    updated = False
                    for u in users:
                        if u["email"].lower() == new_email.lower():
                            u["role"] = new_role
                            u["society"] = new_society
                            updated = True
                    if not updated:
                        users.append({"email": new_email.lower(), "role": new_role, "society": new_society})
                    save_users(users)
                    st.success(f"User '{new_email}' has been added/updated. Please refresh the app.")
                    st.rerun()

            st.markdown("### Delete User")
            user_to_delete = st.selectbox("Select User to Delete", [u["email"] for u in users if u["email"].lower() != user_email])
            if st.button("Delete User"):
                users = [u for u in users if u["email"].lower() != user_to_delete.lower()]
                save_users(users)
                st.warning(f"User '{user_to_delete}' deleted. Please refresh the app.")
                st.rerun()

            # --- SOCIETIES TABLE ---
            societies = read_societies()  # Reload to get updates
            societies_df = pd.DataFrame(societies)
            st.subheader("🏢 Societies Management")
            st.dataframe(societies_df[["name", "activities_url", "logs_url", "logo_url"]], use_container_width=True)

            st.markdown("### Add or Edit Society")
            with st.form("add_edit_society"):
                soc_name = st.text_input("Society Name", "")
                act_url = st.text_input("Activities Sheet URL", "")
                log_url = st.text_input("Logs Sheet URL", "")
                logo_url = st.text_input("Logo URL (optional)", "")
                submit_society = st.form_submit_button("Add / Update Society")
                if submit_society and soc_name and act_url and log_url:
                    societies = read_societies()
                    updated = False
                    for s in societies:
                        if s["name"].lower() == soc_name.lower():
                            s["activities_url"] = act_url
                            s["logs_url"] = log_url
                            s["logo_url"] = logo_url
                            updated = True
                    if not updated:
                        societies.append({"name": soc_name, "activities_url": act_url, "logs_url": log_url, "logo_url": logo_url})
                    save_societies(societies)
                    st.success(f"Society '{soc_name}' added/updated. Please refresh the app.")
                    st.rerun()

            st.markdown("### Delete Society")
            soc_to_delete = st.selectbox("Select Society to Delete", [s["name"] for s in societies])
            if st.button("Delete Society"):
                societies = [s for s in societies if s["name"].lower() != soc_to_delete.lower()]
                save_societies(societies)
                st.warning(f"Society '{soc_to_delete}' deleted. Please refresh the app.")
                st.rerun()

            st.divider()
            st.info("You can now manage users and societies here. Refresh the page after any changes.")

else:
    st.warning("Please log in with your Google account to continue.")
    st.stop()
