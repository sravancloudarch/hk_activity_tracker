import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, date
from uuid import uuid4

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

# --- Sheet URLs or Names ---
ACTIVITIES_URL = st.secrets["sheets"]["activities_url"] if "sheets" in st.secrets else "your_activities_gsheet_url"
LOGS_URL = st.secrets["sheets"]["logs_url"] if "sheets" in st.secrets else "your_logs_gsheet_url"

# ---- Helper Functions ----
def write_df(sheet_url, df, sheet_name="Sheet1"):
    sheet = client.open_by_url(sheet_url)
    ws = sheet.worksheet(sheet_name)
    ws.clear()
    if not df.empty:
        df = df.astype(str)  # Ensure all values are strings for Google Sheets
        ws.update([df.columns.values.tolist()] + df.values.tolist())

def save_logs(df):
    df_to_save = df.copy()
    df_to_save["Date"] = df_to_save["Date"].astype(str)
    # Convert all columns to string before writing
    for col in df_to_save.columns:
        df_to_save[col] = df_to_save[col].astype(str)
    write_df(LOGS_URL, df_to_save)

def save_activities(df):
    df_to_save = df.copy()
    df_to_save["Recurrence"] = df_to_save["Recurrence"].astype(str)
    df_to_save["Tags"] = df_to_save["Tags"].apply(lambda l: ",".join(l) if isinstance(l, list) else l)
    df_to_save["Dependencies"] = df_to_save["Dependencies"].apply(lambda l: ",".join(l) if isinstance(l, list) else l)
    # Convert all columns to string before writing
    for col in df_to_save.columns:
        df_to_save[col] = df_to_save[col].astype(str)
    write_df(ACTIVITIES_URL, df_to_save)

def read_df(sheet_url, sheet_name="Sheet1"):
    sheet = client.open_by_url(sheet_url)
    data = sheet.worksheet(sheet_name).get_all_records()
    return pd.DataFrame(data)

def ensure_id(df):
    if "ID" not in df.columns:
        df["ID"] = [str(uuid4()) for _ in range(len(df))]
    else:
        # Fill any missing or blank IDs, row by row
        df["ID"] = df["ID"].apply(lambda x: str(uuid4()) if pd.isna(x) or str(x).strip() == "" else str(x))
    return df

# ---- Activities ----
def load_activities():
    df = read_df(ACTIVITIES_URL)
    if not df.empty:
        df = ensure_id(df)
        df["Recurrence"] = df["Recurrence"].apply(
            lambda x: eval(x) if isinstance(x, str) and x.startswith("{") else {"type": df["Schedule"] if "Schedule" in df else "daily"}
        )
        df["Tags"] = df.get("Tags", "").apply(lambda x: x.split(",") if isinstance(x, str) else [])
        df["Dependencies"] = df.get("Dependencies", "").apply(lambda x: x.split(",") if isinstance(x, str) else [])
    return df

# ---- Logs ----
def load_logs():
    df = read_df(LOGS_URL)
    if not df.empty and "Date" in df:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])
    return df

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

# ---- Streamlit UI ----
st.set_page_config(page_title="🚦 Sukhii9 Maintenance Activity Tracker App", layout="wide")
st.title("🚦 Sukhii9 Maintenance Activity Tracker App")

activities = load_activities()
logs = load_logs()
today = get_today()

# ----- Sidebar Filters -----
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

# ---- Add/Edit/Delete Activities ----
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
            # Fix: Only supply current_dependencies if they're in dependency_options
            current_dependencies = [d for d in act_row.get("Dependencies", []) if d in dependency_options]
            dep_names = st.multiselect(
                "Dependencies (must complete first)",
                dependency_options,
                default=current_dependencies
            )
            submit = st.form_submit_button("Save Changes")
            if submit:
                idx = activities[activities["ID"] == edit_id].index[0]
                activities.at[idx, "Activity"] = name
                activities.at[idx, "Description"] = desc
                activities.at[idx, "Tags"] = [t.strip() for t in tags if t.strip()]
                activities.at[idx, "Dependencies"] = dep_names
                save_activities(activities)
                st.success("Activity updated. Please refresh the page.")

    elif mode == "Delete" and not activities.empty:
        del_id = st.selectbox(
            "Select Activity",
            activities["ID"],
            format_func=lambda id: activities[activities["ID"] == id]["Activity"].values[0]
        )
        if st.button("Delete Activity"):
            activities = activities[activities["ID"] != del_id].reset_index(drop=True)
            save_activities(activities)
            st.warning("Activity deleted. Please refresh the page.")

# ---- Calendar View ----
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

# ---- Activities Table with Quick Status & Comments ----
st.header("Today's & Overdue Activities")
for _, act in filtered_activities.iterrows():
    overdue = is_overdue(act["ID"], logs, today)
    if show_overdue and not overdue:
        continue
    # Should this be shown today?
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
                            'User': 'NA', 'Timestamp': datetime.now(), 'Overdue': d != today
                        })
                    logs = pd.concat([logs, pd.DataFrame(new_entries)], ignore_index=True)
                    logs["Date"] = pd.to_datetime(logs["Date"], errors="coerce")
                    logs = logs.dropna(subset=["Date"])
                    save_logs(logs)
                    st.success("Marked complete with missed roll-over.")
                    st.experimental_rerun()
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

# ---- Analytics Dashboard ----
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

# ---- Export/Import Data ----
with st.expander("⬇️⬆️ Export/Import Data"):
    st.download_button("Export Activities CSV", data=activities.to_csv(index=False), file_name="activities.csv")
    st.download_button("Export Log CSV", data=logs.to_csv(index=False), file_name="activity_log.csv")

# ---- Dependencies Matrix ----
with st.expander("📦 Activity Dependencies"):
    dep_data = []
    for _, act in activities.iterrows():
        for dep in act.get("Dependencies", []):
            dep_data.append({"Activity": act["Activity"], "Depends On": dep})
    if dep_data:
        st.dataframe(pd.DataFrame(dep_data))
    else:
        st.info("No dependencies set.")
