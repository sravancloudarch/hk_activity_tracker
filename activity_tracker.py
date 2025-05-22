import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta

ACTIVITY_JSON = 'activities.json'
LOG_CSV = 'completion_log.csv'
EXCEL_FILE = 'hk.xlsx'

# ---------- Load/Save Functions ----------
def load_activities():
    if not os.path.exists(ACTIVITY_JSON):
        # First run: Convert Excel to JSON
        xls = pd.ExcelFile(EXCEL_FILE)
        df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])
        df = df[['Activity', 'Description', 'Schedule']].dropna(subset=['Activity'])
        df['Schedule'] = df['Schedule'].str.strip().str.lower()
        activities = df.to_dict(orient='records')
        with open(ACTIVITY_JSON, 'w') as f:
            json.dump(activities, f, indent=2)
        return activities
    else:
        with open(ACTIVITY_JSON, 'r') as f:
            return json.load(f)

def save_activities(activities):
    with open(ACTIVITY_JSON, 'w') as f:
        json.dump(activities, f, indent=2)

def load_log():
    try:
        return pd.read_csv(LOG_CSV)
    except FileNotFoundError:
        return pd.DataFrame(columns=['Date', 'Activity', 'Status', 'Evidence Link'])

def save_log(df):
    df.to_csv(LOG_CSV, index=False)

# ---------- Scheduling Logic ----------
def scheduled_today(activity):
    sched = activity['Schedule']
    now = datetime.now()
    if sched == 'daily':
        return True
    elif sched == 'monthly':
        return now.day == 1
    elif sched in ('monthly twice', 'montly twice'):
        return now.day in [1, 15]
    elif sched == 'weekly':
        return now.weekday() == 0
    return False

def get_by_schedule_type(acts, schedule_type):
    if schedule_type == "all":
        return acts
    return [a for a in acts if a["Schedule"] == schedule_type]

def filter_history(log, acts, schedule_type, from_date, to_date, search_term=None):
    filtered = log.copy()
    if schedule_type != "all":
        act_names = [a["Activity"] for a in acts if a["Schedule"] == schedule_type]
        filtered = filtered[filtered["Activity"].isin(act_names)]
    if from_date:
        filtered = filtered[filtered["Date"] >= from_date]
    if to_date:
        filtered = filtered[filtered["Date"] <= to_date]
    if search_term:
        mask = filtered['Activity'].str.contains(search_term, case=False, na=False) | \
               filtered['Status'].str.contains(search_term, case=False, na=False) | \
               filtered['Evidence Link'].str.contains(search_term, case=False, na=False)
        filtered = filtered[mask]
    return filtered

# ---------- Main App ----------
activities = load_activities()
log = load_log()
today = datetime.now().strftime('%Y-%m-%d')

st.title("Activity Schedule Tracker (JSON Backend)")

# ---------- Sidebar Filters ----------
st.sidebar.header("Filter Activities")
schedule_types = ["all", "daily", "weekly", "monthly", "monthly twice"]
selected_schedule = st.sidebar.selectbox("Show schedule type", schedule_types, index=0)
show_history = st.sidebar.checkbox("Show Activity History", value=False)
search_text = st.sidebar.text_input("Search (Activity/Evidence/Status)")

# ---------- Today's Activities or Schedule-type History ----------
if not show_history:
    st.header("Today's Activities")
    scheduled = [a for a in activities if scheduled_today(a)]
    scheduled = get_by_schedule_type(scheduled, selected_schedule)
    if not scheduled:
        st.warning(f"No scheduled activities for today for the '{selected_schedule.capitalize()}' filter.")

        # Show all activities of this schedule type, with their past status (history table)
        filtered_activities = get_by_schedule_type(activities, selected_schedule)
        if search_text:
            filtered_activities = [
                a for a in filtered_activities
                if search_text.lower() in a["Activity"].lower() or
                   search_text.lower() in (a.get("Description") or "").lower()
            ]
        if not filtered_activities:
            st.info(f"No activities of type '{selected_schedule}' with this search.")
        else:
            st.subheader(f"{selected_schedule.capitalize()} Activities History")
            num_rows = st.slider("Show up to N recent records per activity", min_value=1, max_value=30, value=10)
            for activity in filtered_activities:
                act_name = activity["Activity"]
                act_desc = activity["Description"]
                st.markdown(f"**{act_name}**  \n_{act_desc}_")
                # Filter log for this activity (show up to num_rows)
                recent_log = log[log["Activity"] == act_name]
                if not recent_log.empty:
                    if search_text:
                        recent_log = recent_log[
                            recent_log["Evidence Link"].str.contains(search_text, case=False, na=False) |
                            recent_log["Status"].str.contains(search_text, case=False, na=False)
                        ]
                    recent_log = recent_log.sort_values(by="Date", ascending=False).head(num_rows)
                    st.dataframe(
                        recent_log[["Date", "Status", "Evidence Link"]],
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.caption("No completion records for this activity.")
                st.divider()
    else:
        for activity in scheduled:
            name = activity['Activity']
            desc = activity['Description']
            st.subheader(name)
            st.caption(desc)
            existing = log[(log['Date'] == today) & (log['Activity'] == name)]
            if not existing.empty:
                st.success("Completed! Evidence: " + str(existing.iloc[0]['Evidence Link']))
            else:
                with st.form(f'form_{name}'):
                    st.write("Status:")
                    completed = st.checkbox("Mark as Completed")
                    evidence = st.text_input("Evidence Link (URL, e.g., Google Photos)")
                    submitted = st.form_submit_button("Save")
                    if submitted:
                        if completed and evidence:
                            new_entry = pd.DataFrame([{
                                'Date': today,
                                'Activity': name,
                                'Status': 'Completed',
                                'Evidence Link': evidence
                            }])
                            log = pd.concat([log, new_entry], ignore_index=True)
                            save_log(log)
                            st.success("Saved!")
                        else:
                            st.warning("Please check completed and provide an evidence link.")

# ---------- Activity History with Search, Filters, Date Range ----------
if show_history:
    st.header("Activity Completion History")
    col1, col2 = st.columns(2)
    with col1:
        from_date = st.date_input("From Date", value=datetime.now() - timedelta(days=7))
    with col2:
        to_date = st.date_input("To Date", value=datetime.now())
    from_date_str = from_date.strftime('%Y-%m-%d')
    to_date_str = to_date.strftime('%Y-%m-%d')
    filtered_history = filter_history(log, activities, selected_schedule, from_date_str, to_date_str, search_text)
    filtered_history = filtered_history.sort_values(by='Date', ascending=False)
    st.dataframe(filtered_history, use_container_width=True)

    st.download_button(
        label="Download Filtered History (CSV)",
        data=filtered_history.to_csv(index=False),
        file_name="filtered_activity_history.csv"
    )

st.divider()
# ---------- Add New Activity (append to JSON) ----------
st.header("Add New Activity")
with st.form('add_activity'):
    act = st.text_input("Activity Name")
    desc = st.text_area("Description")
    sched = st.selectbox("Schedule", ["daily", "weekly", "monthly", "monthly twice"])
    add_btn = st.form_submit_button("Add Activity")
    if add_btn and act:
        new_act = {"Activity": act, "Description": desc, "Schedule": sched}
        activities.append(new_act)
        save_activities(activities)
        st.success(f"Added '{act}' to activities. Will appear as per its schedule.")


