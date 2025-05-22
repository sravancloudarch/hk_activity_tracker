import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta, date
from uuid import uuid4

# ------------- CONFIGURATION -------------
ACTIVITY_JSON = 'activities.json'
LOG_CSV = 'completion_log.csv'
AVATAR_FOLDER = 'avatars'  # Place activity avatars/icons here

# ------------- UTILITY FUNCTIONS -------------
def load_activities():
    if not os.path.exists(ACTIVITY_JSON):
        return []
    with open(ACTIVITY_JSON, 'r') as f:
        return json.load(f)

def save_activities(activities):
    with open(ACTIVITY_JSON, 'w') as f:
        json.dump(activities, f, indent=2)

def load_log():
    try:
        log = pd.read_csv(LOG_CSV)
        if not log.empty:
            log["Date"] = pd.to_datetime(log["Date"], errors="coerce")
            log = log.dropna(subset=["Date"])
        return log
    except FileNotFoundError:
        return pd.DataFrame(columns=[
            'Date', 'ActivityID', 'Status', 'Evidence Link', 'Comments', 'User', 'Timestamp', 'Overdue'
        ])

def save_log(df):
    df.to_csv(LOG_CSV, index=False)

def get_today():
    return date.today()

def is_overdue(activity_id, log, today):
    records = log[(log["ActivityID"] == activity_id)]
    if not records.empty:
        last_done = records["Date"].max()
        return last_done.date() < today
    return True

def archive_old_logs(log):
    cutoff = datetime.now() - timedelta(days=120)
    active = log[log["Date"] >= cutoff]
    archived = log[log["Date"] < cutoff]
    if not archived.empty:
        archived.to_csv('archived_log.csv', mode='a', header=not os.path.exists('archived_log.csv'), index=False)
    return active

def get_activity_by_id(activities, act_id):
    for a in activities:
        if a["ID"] == act_id:
            return a
    return None

def recurrence_matches_today(recurrence, today):
    if not recurrence:
        return False
    if recurrence.get("type") == "daily":
        return True
    elif recurrence.get("type") == "weekly":
        return today.weekday() in recurrence.get("days", [])
    elif recurrence.get("type") == "monthly":
        return today.day in recurrence.get("days", [1])
    elif recurrence.get("type") == "custom":
        return today.weekday() in recurrence.get("days", [])
    return False

def can_mark_complete(act, activities, log):
    for dep in act.get("Dependencies", []):
        dep_act = next((a for a in activities if a["Activity"] == dep), None)
        if dep_act:
            dep_id = dep_act["ID"]
            today = get_today()
            done_today = not log[(log["ActivityID"] == dep_id) & (log["Date"] == pd.Timestamp(today))].empty
            if not done_today:
                return False
    return True

# ------------- STREAMLIT APP START -------------

st.set_page_config(page_title="Activity Tracker", layout="wide")

if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False

dark_mode = st.sidebar.toggle("🌙 Dark Mode", value=st.session_state["dark_mode"])
st.session_state["dark_mode"] = dark_mode

if dark_mode:
    st.markdown(
        """
        <style>
            .stApp { background-color: #181818; color: #FFF; }
        </style>
        """,
        unsafe_allow_html=True,
    )

st.title("🚦 Sukhii9 Maintenance Activity Tracker App")

# ------------ DATA LOAD / INIT ------------
activities = load_activities()
log = load_log()
log = archive_old_logs(log)
save_log(log)
today = get_today()

# ------------ SIDEBAR: SCHEDULE TYPE FILTER & SEARCH ------------
st.sidebar.header("🔎 Filter & Search")
schedule_types = ["all", "daily", "weekly", "monthly", "custom"]
selected_schedule = st.sidebar.selectbox("Show schedule type", schedule_types, index=0)
search_term = st.sidebar.text_input("Search Activities")
show_overdue = st.sidebar.checkbox("Show only overdue", value=False)
history_rows = st.sidebar.slider("Show up to N history records/activity", min_value=5, max_value=50, value=10)

def matches_filters(act):
    schedule_match = selected_schedule == "all" or act.get("Schedule", "daily") == selected_schedule
    search_match = (search_term == "") or (search_term.lower() in act["Activity"].lower()) or (search_term.lower() in (act.get("Description") or "").lower())
    return schedule_match and search_match

filtered_activities = [a for a in activities if matches_filters(a)]

# ------------ ADD/EDIT/DELETE ACTIVITIES ------------
with st.expander("➕ Add / ✏️ Edit / 🗑️ Delete Activities", expanded=len(activities)==0):
    mode = st.selectbox("Choose Action", ["Add", "Edit", "Delete"])
    if mode == "Add":
        with st.form("add_form"):
            name = st.text_input("Activity Name")
            desc = st.text_area("Description")
            tags = st.text_input("Tags (comma separated)").split(",")
            avatar = st.file_uploader("Avatar/Icon", type=["png", "jpg", "jpeg"])
            schedule_type = st.selectbox("Schedule Type", ["daily", "weekly", "monthly", "custom"])
            if schedule_type == "custom" or schedule_type == "weekly":
                rec_days = st.multiselect("Repeat on days", [0,1,2,3,4,5,6], format_func=lambda x: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][x])
            elif schedule_type == "monthly":
                rec_days = st.multiselect("Repeat on dates", list(range(1,29)))
            else:
                rec_days = []
            recurrence = {"type": schedule_type, "days": rec_days} if rec_days else {"type": schedule_type}
            dep_names = st.multiselect("Dependencies (must complete first)", [a["Activity"] for a in activities])
            submit = st.form_submit_button("Add Activity")
            if submit and name:
                new_id = str(uuid4())
                filename = ""
                if avatar:
                    os.makedirs(AVATAR_FOLDER, exist_ok=True)
                    filename = f"{AVATAR_FOLDER}/{new_id}_{avatar.name}"
                    with open(filename, "wb") as f:
                        f.write(avatar.read())
                new_activity = {
                    "Activity": name,
                    "Description": desc,
                    "Schedule": schedule_type,
                    "Recurrence": recurrence,
                    "Tags": [t.strip() for t in tags if t.strip()],
                    "Avatar": filename,
                    "Dependencies": dep_names,
                    "ID": new_id
                }
                activities.append(new_activity)
                save_activities(activities)
                st.success(f"Activity '{name}' added! Refresh page to see in main list.")

    elif mode == "Edit" and activities:
        edit_id = st.selectbox("Select Activity", [a["ID"] for a in activities], format_func=lambda id: next(a["Activity"] for a in activities if a["ID"] == id))
        act = get_activity_by_id(activities, edit_id)
        with st.form("edit_form"):
            name = st.text_input("Activity Name", value=act["Activity"])
            desc = st.text_area("Description", value=act.get("Description",""))
            tags = st.text_input("Tags (comma separated)", value=",".join(act.get("Tags",[]))).split(",")
            dep_names = st.multiselect("Dependencies (must complete first)", [a["Activity"] for a in activities if a["ID"] != edit_id], default=act.get("Dependencies",[]))
            submit = st.form_submit_button("Save Changes")
            if submit:
                act["Activity"] = name
                act["Description"] = desc
                act["Tags"] = [t.strip() for t in tags if t.strip()]
                act["Dependencies"] = dep_names
                save_activities(activities)
                st.success("Activity updated. Refresh page to see changes.")

    elif mode == "Delete" and activities:
        del_id = st.selectbox("Select Activity", [a["ID"] for a in activities], format_func=lambda id: next(a["Activity"] for a in activities if a["ID"] == id))
        if st.button("Delete Activity"):
            activities = [a for a in activities if a["ID"] != del_id]
            save_activities(activities)
            st.warning("Activity deleted. Refresh page to update.")

# ------------ CALENDAR VIEW ------------
with st.expander("📅 Calendar View"):
    calendar_days = [today - timedelta(days=i) for i in range(30)][::-1]
    calendar_df = pd.DataFrame({"Date": calendar_days})
    for act in filtered_activities:
        act_id = act["ID"]
        if not log.empty:
            completed_days = set(log[log["ActivityID"] == act_id]["Date"].dt.date)
        else:
            completed_days = set()
        calendar_df[act["Activity"]] = calendar_df["Date"].apply(lambda d: "✅" if d in completed_days else "❌")
    st.dataframe(calendar_df.set_index("Date"), use_container_width=True)

# ------------ ACTIVITIES TABLE WITH QUICK STATUS & COMMENTS ------------
st.header("Today's & Overdue Activities")

for act in filtered_activities:
    overdue = is_overdue(act["ID"], log, today)
    if show_overdue and not overdue:
        continue
    # Should this be shown today?
    if not recurrence_matches_today(act.get("Recurrence", {"type": act.get("Schedule", "daily")}), today) and not overdue:
        continue
    # Dependencies met?
    dep_met = can_mark_complete(act, activities, log)
    c1, c2, c3 = st.columns([1,5,3])
    with c1:
        if act.get("Avatar") and os.path.exists(act["Avatar"]):
            st.image(act["Avatar"], width=60)
        else:
            st.write("")
    with c2:
        st.markdown(f"**{act['Activity']}**")
        st.caption(act.get("Description",""))
        st.markdown(f"Tags: {' '.join(['#'+t for t in act.get('Tags',[])])}")
        if overdue:
            st.markdown("**:red[Overdue!]**")
        if act.get("Dependencies"):
            st.markdown(f"Depends on: {', '.join(act['Dependencies'])}")
        # Completion/comments
        done_today = not log[(log["ActivityID"]==act["ID"]) & (log["Date"]==pd.Timestamp(today))].empty
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
                        past = log[log["ActivityID"]==act["ID"]]
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
                    log = pd.concat([log, pd.DataFrame(new_entries)], ignore_index=True)
                    log["Date"] = pd.to_datetime(log["Date"], errors="coerce")
                    log = log.dropna(subset=["Date"])
                    save_log(log)
                    st.success("Marked complete with missed roll-over.")
                    st.experimental_rerun()
        else:
            st.warning("Dependencies not completed today.")

    with c3:
        recent_log = log[log["ActivityID"] == act["ID"]].sort_values(by="Date", ascending=False).head(history_rows)
        if not recent_log.empty:
            st.write("Recent History:")
            st.dataframe(recent_log[["Date", "Status", "Evidence Link", "Comments"]], use_container_width=True, hide_index=True)
        else:
            st.caption("No history for this activity.")

# ------------ ANALYTICS DASHBOARD ------------
with st.expander("📊 Analytics Dashboard"):
    st.markdown("**Completion Trends (last 30 days)**")
    df = log[log["Date"] >= (datetime.now()-timedelta(days=30))]
    if not df.empty:
        summary = df.groupby('ActivityID').agg(Count=('Status','count')).reset_index()
        summary['Activity'] = summary['ActivityID'].map({a['ID']:a['Activity'] for a in activities})
        st.bar_chart(summary.set_index('Activity')['Count'])
    else:
        st.info("No completion data yet.")

# ------------ EXPORT / IMPORT ------------
with st.expander("⬇️⬆️ Export/Import Data"):
    st.download_button("Export Activities JSON", data=json.dumps(activities,indent=2), file_name="activities.json")
    st.download_button("Export Log CSV", data=log.to_csv(index=False), file_name="activity_log.csv")
    uploaded_json = st.file_uploader("Import Activities JSON", type="json")
    if uploaded_json:
        activities = json.load(uploaded_json)
        save_activities(activities)
        st.success("Imported activities JSON. Refresh page to reload.")

    uploaded_csv = st.file_uploader("Import Log CSV", type="csv")
    if uploaded_csv:
        log = pd.read_csv(uploaded_csv)
        if not log.empty:
            log["Date"] = pd.to_datetime(log["Date"], errors="coerce")
            log = log.dropna(subset=["Date"])
        save_log(log)
        st.success("Imported activity log. Refresh page to reload.")

# ------------ DEPENDENCIES MATRIX ------------
with st.expander("📦 Activity Dependencies"):
    dep_data = []
    for act in activities:
        for dep in act.get("Dependencies", []):
            dep_data.append({"Activity": act["Activity"], "Depends On": dep})
    if dep_data:
        st.dataframe(pd.DataFrame(dep_data))
    else:
        st.info("No dependencies set.")
