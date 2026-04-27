import streamlit as st
import requests
import pandas as pd
import numpy as np
# import plotly.graph_objects as go 
# import plotly.express as px
# from datetime import datetime, timedelta

APP_ID = st.secrets["Larksuite"]["APP_ID"]
APP_SECRET = st.secrets["Larksuite"]["APP_SECRET"]
APP_TOKEN = "Bu3QbY095aE5H1sdXtvjoRG4pjb"
TABLE_ID = "tbldXd7TSURHd0sI"
TABLE_ID_1 = "tblJ1I75LphH4suv"

# 2. 获取访问令牌 Tenant Access Token
# @st.cache_data(ttl=7000) # 缓存 token，避免频繁请求
def get_tenant_access_token():
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    r = requests.post(url, json=payload)
    return r.json().get("tenant_access_token")


def fetch_bitable_data(table_id):
    token = get_tenant_access_token()
    
    if not token:
        st.error("❌ token 获取失败")
        return pd.DataFrame()

    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}

    all_items = []
    page_token = None

    while True:
        params = {}
        if page_token:
            params["page_token"] = page_token

        res = requests.get(url, headers=headers, params=params)
        data = res.json()

        if data.get("code") != 0:
            st.error(f"❌ 抓取失败: {data}")
            return pd.DataFrame()

        items = data.get("data", {}).get("items", [])
        all_items.extend(items)

        # 👉 关键：判断是否还有下一页
        if not data.get("data", {}).get("has_more"):
            break

        page_token = data.get("data", {}).get("page_token")

    return pd.DataFrame([i["fields"] for i in all_items])
        
leases_df = pd.read_csv("Leases.csv")
lark_df_USC = fetch_bitable_data(TABLE_ID) 
lark_df_UCLA = fetch_bitable_data(TABLE_ID_1)

lark_df_UCLA = lark_df_UCLA[[
    "Unit - Room Number",
    "Rental Price",
    "Lease Status"
]].copy()

lark_df_UCLA = lark_df_UCLA.rename(columns={
    "Unit - Room Number": "Room Number",
    "Rental Price": "Real Price"
})

lark_df_UCLA["Monthly Concession"] = 0

lark_df_USC = lark_df_USC[[
    'Room Number',
    'Real Price',
    'Lease Status',
    'Monthly Concession'
]].copy()
lark_df_UCLA = lark_df_UCLA[[
    'Room Number',
    'Real Price',
    'Monthly Concession',
    'Lease Status'
]].copy()

lark_df = pd.concat([lark_df_USC, lark_df_UCLA], ignore_index=True)

leases_df['Room Number'] = leases_df['Room Number'].astype(str).str.strip()
lark_df['Room Number'] = lark_df['Room Number'].astype(str).str.strip()

merged_df = pd.merge(
    leases_df, 
    lark_df[['Room Number', 'Real Price','Lease Status', 'Monthly Concession']], 
    on='Room Number', 
    how='left'
)

merged_df['Real Price'] = pd.to_numeric(merged_df['Real Price'], errors='coerce').fillna(0)
merged_df['Monthly Concession'] = pd.to_numeric(merged_df['Monthly Concession'], errors='coerce').fillna(0)
merged_df['Net Rent'] = merged_df['Real Price'] - merged_df['Monthly Concession']
cost_df = pd.read_csv("Cost.csv")
property_df = pd.read_csv("Property.csv")
cost_df.columns = cost_df.columns.str.strip()
cost_cols = ['Mortgage Loan Interest', 'Insurance', 'Tax', 'Other Fixed']
for col in cost_cols:
    if col in cost_df.columns:
        # 先转成字符串，去掉逗号，再转成数字
        cost_df[col] = pd.to_numeric(
            cost_df[col].astype(str).str.replace(',', '').str.strip(), 
            errors='coerce'
        ).fillna(0)
cost_df['Total_Fixed'] = cost_df[cost_cols].sum(axis=1)
cost_summary = cost_df[['Property ID', 'Total_Fixed']]

signed_leases_df = merged_df[merged_df['Lease Status'] == 'Lease Signed'].copy()

leased_info = signed_leases_df.groupby('Property ID').agg(
    Leased_Units=('Room Number', 'count'),          # 这里统计的就是已签约的房间数了
    Already_Leased_Rev=('Net Rent', 'sum') # 这里统计的就是已签约的总净租金
).reset_index()

# 3. 然后再与 property_df 合并
final_df = property_df.merge(cost_summary, on='Property ID', how='left') \
                      .merge(leased_info, on='Property ID', how='left')

final_df['Already_Leased_Rev'] = final_df['Already_Leased_Rev'].fillna(0)
st.dataframe(final_df)
