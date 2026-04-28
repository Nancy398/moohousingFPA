import streamlit as st
import requests
import pandas as pd
import numpy as np
# import plotly.graph_objects as go 
import plotly.express as px
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
final_df['Leased_Units'] = final_df['Leased_Units'].fillna(0)

def calculate_detailed_profit(row):
    # 初始化所有明细为 0
    mgt_fee = 0.0
    labor = 0.0
    commission = 0.0
    marketing = 0.0
    bookkeeping = 0.0
    
    p_type = row['Type']
    rev = row['Already_Leased_Rev']
    unit = row['Leased_Units']
    total_unit = row['Total Unit']
    fixed = row['Total_Fixed']

    if p_type == "MH":
        # MH 的明细计算逻辑（根据你的需求调整比例）
        mgt_fee = rev * 0.08
        labor = rev * 0.04
        commission = unit * 50
        marketing = total_unit * 30
        bookkeeping = 200  # 假设固定值
        # MH 总利润 = 收益项 - 成本项 (这里假设 mgt_fee 和 labor 是收益)
        profit = mgt_fee + labor + commission + marketing + bookkeeping
        
    elif p_type == "ML":
        # ML 通常只有毛利逻辑
        profit = rev * 0.98 - fixed
        # 如果 ML 不需要明细，其他字段保持 0 即可   
    else:
        profit = 0

    # 返回一个 Series，索引名称就是列名
    return pd.Series({
        'Management_Fee': mgt_fee,
        'Labor': labor,
        'Commission': commission,
        'Marketing': marketing,
        'Bookkeeping': bookkeeping,
        'Profit': profit
    })

# --- 应用到 DataFrame ---
# 将生成的 6 列合并到原有的 final_df 中
detail_cols = final_df.apply(calculate_detailed_profit, axis=1)
final_df = pd.concat([final_df, detail_cols], axis=1)
    
st.dataframe(final_df)

st.title("🏙️ Financial Dashboard")

# --- 第一层：选择类型 ---
selected_type = st.selectbox("Select Type", options=["MH", "ML"])

# 过滤数据
type_df = final_df[final_df['Type'] == selected_type]

# --- 第二层：展示总体 Profit 和分项 ---
st.subheader(f"📊 {selected_type} Summary")

col1, col2 = st.columns([1, 2])

with col1:
    total_profit = type_df['Profit'].sum()
    st.metric(label=f"{selected_type} Total Profit", value=f"${total_profit:,.2f}")
    
    # 如果是 MH，展示分项总和
    if selected_type == "MH":
        st.write("**Breakdown:**")
        st.write(f"- Management Fee: ${type_df['Management_Fee'].sum():,.0f}")
        st.write(f"- Labor: ${type_df['Labor'].sum():,.0f}")
        st.write(f"- Commission: ${type_df['Commission'].sum():,.0f}")
        st.write(f"- Marketing: ${type_df['Marketing'].sum():,.0f}")
        st.write(f"- Bookkeeping: ${type_df['Bookkeeping'].sum():,.0f}")


with col2:
    if selected_type == "MH":
        # 准备饼图数据（仅展示收益和支出的构成）
        mh_summary = type_df[['Management_Fee', 'Labor', 'Commission', 'Marketing', 'Bookkeeping']].sum()
        # 将支出项转为正数用于绘图
        plot_data = mh_summary.abs()
        fig = px.pie(values=plot_data.values, names=plot_data.index, title=f"{selected_type} Profit Structure")
        st.plotly_chart(fig, use_container_width=True)
    else:
        # ML 类型的简单展示
        col1, col2 = st.columns([1, 2])
        with col1:
            total_rev =  type_df['Already_Leased_Rev']
            st.metric(label=f"{selected_type} Total Revenue", value=f"${total_rev:,.2f}")
        with col2:
            total_cost =  type_df['Total_Fixed']
            st.metric(label=f"{selected_type} Total Cost", value=f"${total_cost:,.2f}")
        

st.markdown("---")

# --- 第三层：选地块/具体项目 ---
st.header(f"📍 {selected_type} Detailed")

# 获取当前类型下的所有地块名称
locations = type_df['Property ID'].unique() # 假设你的列名是 Property_Name
selected_location = st.selectbox("Please select property", options=locations)

# 过滤具体地点的数据
location_data = type_df[type_df['Property ID'] == selected_location].iloc[0]

# 展示单地块详情
c1, c2, c3 = st.columns(3)
c1.write(f"**Total Profit**")
c1.subheader(f"${location_data['Profit']:,.2f}")

with st.expander("点击查看该地块详细核算明细"):
    # 用表格展示该行的所有财务列
    detail_view = location_data[['Management_Fee', 'Labor', 'Commission', 'Marketing', 'Bookkeeping', 'Profit']]
    st.table(detail_view)

# (可选) 展示该地块在同类中的表现
st.bar_chart(type_df.set_index('Property ID')['Profit'])
