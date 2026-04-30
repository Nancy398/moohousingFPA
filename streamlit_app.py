import streamlit as st
import requests
import pandas as pd
import numpy as np
# import plotly.graph_objects as go 
import plotly.express as px
# from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
import gspread
import datetime
from gspread_dataframe import set_with_dataframe

st.set_page_config(page_title="Property Strategy", layout="wide")
tab_overview, tab_apartments = st.tabs(["📊 Property Overview", "🏢 Apartments"])

with tab_overview:
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
    cost_summary = cost_df[['Property ID', 'Total_Fixed','Marketing','Bookkeeping']]
    
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
    
    st.dataframe(final_df)
    
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
        marketing = row['Marketing']
        bookkeeping= row['Bookkeeping']
    
        if p_type == "MH":
            # MH 的明细计算逻辑（根据你的需求调整比例）
            mgt_fee = rev * 0.08
            labor = rev * 0.04
            commission = unit * 50
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
            col1, col2 = st.columns([2, 2])
            with col1:
                total_rev =  type_df['Already_Leased_Rev'].sum()
                st.metric(label=f"{selected_type} Total Revenue", value=f"${total_rev:,.2f}")
            with col2:
                total_cost =  type_df['Total_Fixed'].sum()
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
    col_p1, col_p2, col_p3 = st.columns(3)
    with col_p1:
        st.metric(label="Total Profit", value=f"${location_data['Profit']:,.2f}")
    with col_p2:
        st.metric(label="Revenue", value=f"${location_data['Already_Leased_Rev']:,.2f}")
    with col_p3:
        st.metric(label="Occupancy Rate", value=f"{(location_data['Leased_Units']/location_data['Total Unit']*100):.1f}%")
    
    st.write("---") # 分割线
    
    # 定义第二行：MH 专有的费用明细 (KPI 形式)
    if selected_type == "MH":
        st.subheader("Cost & Fee Breakdown")
        # 我们用 5 列来展示 5 个细分科目
        m1, m2, m3, m4, m5 = st.columns(5)
        c1, c2, c3 = st.columns(3)
        c1.metric("Management Fee", f"${location_data['Management_Fee']:,.2f}")
        c2.metric("Labor Fee", f"${location_data['Labor']:,.2f}")
        c3.metric("Commission", f"${location_data['Commission']:,.2f}")
        
        # 第二行：辅助收入
        c4, c5 = st.columns(2)
        c4.metric("Marketing Fee", f"${location_data['Marketing']:,.2f}")
        c5.metric("Bookkeeping Fee", f"${location_data['Bookkeeping']:,.2f}")
    
    else:
        # 如果是 ML，展示 ML 相关的 KPI
        st.subheader("Master Lease Details")
        m1, m2 = st.columns(2)
        m1.metric(label="Fixed Cost", value=f"${location_data['Total_Fixed']:,.0f}", delta_color="inverse")
        m2.metric(label="Revenue", value=f"${location_data['Already_Leased_Rev']*0.98:,.2f}")
    
    # (可选) 展示该地块在同类中的表现
    st.bar_chart(type_df.set_index('Property ID')['Profit'])
with tab_apartments:
    @st.cache_data(ttl=300)
    def read_file(name, sheet, header_row=0):
        """
        header_row: 表头所在的行索引（0 代表第 1 行，1 代表第 2 行，依此类推）
        """
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(
            st.secrets["GOOGLE_APPLICATION_CREDENTIALS"], 
            scopes=scope
        )
        gc = gspread.authorize(credentials)
        worksheet = gc.open(name).worksheet(sheet)
        rows = worksheet.get_all_values() 
        raw_df = pd.DataFrame(rows)
    
        if raw_df.empty:
            return raw_df
        # 1. 根据传入的 header_row 动态提取表头
        new_header = raw_df.iloc[header_row].str.strip().tolist()
            
        # 2. 核心修复：处理重复或空列名（逻辑保持不变）
        final_header = []
        counts = {}
        for i, col in enumerate(new_header):
            name_val = col if col and col != "" else f"Column_{i}"
            if name_val in counts:
                counts[name_val] += 1
                final_header.append(f"{name_val}_{counts[name_val]}")
            else:
                counts[name_val] = 0
                final_header.append(name_val)
    
        # 3. 动态切片：数据从 header_row 的下一行开始取
        df = pd.DataFrame(raw_df.values[header_row + 1:], columns=final_header)
            
        # 4. 去掉全为空的行
        df = df.dropna(how='all').reset_index(drop=True)
        return df

    def get_dynamic_dso(df_list):
        """
        df_list: 包含所有年份 DataFrame 的列表，例如 [df_2025, df_2026]
        """
        # 1. 合并所有历史数据
        df_all_history = pd.concat(df_list, ignore_index=True)
        # 2. 清洗日期格式
        df_all_history['Move-in Date'] = pd.to_datetime(df_all_history['入住时间'], errors='coerce')
        df_all_history['Received Date'] = pd.to_datetime(df_all_history['Receive date'], errors='coerce')
        # 3. 筛选已回款的“成功案例”
        paid_mask = (
            (df_all_history['Received'] == "TRUE") & 
            df_all_history['Move-in Date'].notna() & 
            df_all_history['Received Date'].notna()
        )
        history_paid = df_all_history[paid_mask].copy()
        st.write(history_paid)
        
        # 4. 计算回款周期并剔除异常值（比如负数或超过一年的离群点）
        history_paid['days'] = (history_paid['Received Date'] - history_paid['Move-in Date']).dt.days
        # history_paid = history_paid[(history_paid['days'] > 0) & (history_paid['days'] < 365)]
        st.write(history_paid)
        # 5. 生成公寓映射表和全局平均值
        dso_map = history_paid.groupby('Apartment')['days'].mean().to_dict()
        global_avg = history_paid['days'].mean() if not history_paid.empty else 45
        
        return dso_map, global_avg
    # 同时读取两年数据
    df_2025 = read_file("Apartment Referral List", "2025", header_row=1)
    df_2026 = read_file("Apartment Referral List", "2026", header_row=1)
    
    # 获取基于全量数据的经验模型
    dso_map, global_avg = get_dynamic_dso([df_2025, df_2026])
    st.write(dso_map)
    st.write(global_avg)
    
    # 预测逻辑（针对当前选中的年份 df_curr）
    # def apply_prediction(row):
    #     if row['Received'] == True:
    #         return row['Received Date']
        
    #     move_in = pd.to_datetime(row['Move-in Date'], errors='coerce')
    #     if pd.isna(move_in): return None
        
    #     # 优先查该公寓历史，没有则用全局平均
    #     avg_days = dso_map.get(row['Apartment'], global_avg)
    #     return move_in + pd.Timedelta(days=int(avg_days))
    
    # df_curr['Predicted_Date'] = df_curr.apply(apply_prediction, axis=1)
    with st.container():
        select_year = st.segmented_control(
            "选择年份",
            options=[2025, 2026],
            default=2026,  # 默认高亮 2026
            label_visibility="collapsed" # 隐藏多余标签
        )
    st.title(f"📊 {select_year} Apartments Analysis")
    st.divider()
    select_year = str(select_year)
    df_curr = read_file("Apartment Referral List",select_year,header_row=1)
    df_expense = read_file("Apartments FA","Expense")
    df_curr['Received Commission'] = (
        df_curr['Received Commission']
        .astype(str)
        .str.replace(r'[¥$,]', '', regex=True) # 同时兼容 ￥, $ 和 逗号
        .replace('nan', '0')                  # 处理空值转成的字符串 'nan'
    )
    df_curr['Bonus to resident'] = (
        df_curr['Bonus to resident']
        .astype(str)
        .str.replace(r'[¥$,]', '', regex=True) # 同时兼容 ￥, $ 和 逗号
        .replace('nan', '0')                  # 处理空值转成的字符串 'nan'
    )
    df_expense['Commission'] = (
        df_expense['Commission']
        .astype(str)
        .str.replace(r'[¥$,]', '', regex=True) # 同时兼容 ￥, $ 和 逗号
        .replace('nan', '0')                  # 处理空值转成的字符串 'nan'
    )
    df_expense['Expense'] = (
        df_expense['Expense']
        .astype(str)
        .str.replace(r'[¥$,]', '', regex=True) # 同时兼容 ￥, $ 和 逗号
        .replace('nan', '0')                  # 处理空值转成的字符串 'nan'
    )
    df_curr['Commission'] = (
        df_curr['Commission']
        .astype(str)
        .str.replace(r'[¥$,]', '', regex=True) # 同时兼容 ￥, $ 和 逗号
        .replace('nan', '0')                  # 处理空值转成的字符串 'nan'
    )
    df_curr['Received Commission'] = pd.to_numeric(df_curr['Received Commission'], errors='coerce').fillna(0)
    df_curr['Bonus to resident'] = pd.to_numeric(df_curr['Bonus to resident'], errors='coerce').fillna(0)
    df_curr['Commission'] = pd.to_numeric(df_curr['Commission'], errors='coerce').fillna(0)
    df_expense['Commission'] = pd.to_numeric(df_expense['Commission'], errors='coerce').fillna(0)
    df_expense['Expense'] = pd.to_numeric(df_expense['Expense'], errors='coerce').fillna(0)
    # st.dataframe(df_expense)
    mask_unreceived = (df_curr['状态'] == '已入住')& (df_curr['Received'] == 'FALSE')
    df_unreceived = df_curr[mask_unreceived]
    count_unreceived = len(df_unreceived)
    total_received_commission = df_curr.loc[df_curr['Received'] == 'TRUE', 'Received Commission'].sum()
    payroll_paid_val = df_curr[(df_curr['Payroll'] == 'TRUE') & (df_curr['Received'] == 'TRUE')]['Received Commission'].sum()
    payroll_pending_received_val = df_curr[(df_curr['Payroll'] == 'FALSE') & (df_curr['Received'] == 'TRUE')]['Received Commission'].sum()
    paid_comm_curr = df_expense[(df_expense['Year'] == select_year)]['Commission'].sum()
    other_expense_curr = df_expense[(df_expense['Year'] == select_year)]['Expense'].sum()
    bonus_residents_curr = df_curr['Bonus to resident'].sum()
    total_expense = other_expense_curr + bonus_residents_curr
    checked_in_count = len(df_curr[df_curr['状态'] == '已入住'])
    received_count = checked_in_count-count_unreceived
    expect_commission = df_curr.loc[df_curr['Received'] == 'FALSE', 'Commission'].sum()
    mask_unknown = (df_curr['Received'] == 'FALSE') & (df_curr['Commission'] == 0)&(df_curr['状态'] == '已入住')
    df_unknown = df_curr[mask_unknown]
    unknown_commssion = len(df_unknown)
    realized_NI = total_received_commission - total_expense - paid_comm_curr - payroll_pending_received_val*0.15
    expected_NI = expect_commission * 0.85
    total_NI = realized_NI+expected_NI
    NI_per_room =realized_NI/checked_in_count

# --- 2. 从 df_expense 计算指标 ---
    col1, col2,col3,col4 = st.columns(4)
    col1.metric("已入住总数", f"{int(checked_in_count)}")
    col2.metric("已收commission总数", f"{int(received_count)}")
    col3.metric("Pending Received记录数 (已入住)", f"{count_unreceived}")
    col4.metric("Already received", f"${total_received_commission:,.2f}")

    col1, col2,col3,col4 = st.columns(4)
    with col1:
        st.metric("Paid Commission", f"${paid_comm_curr:,.2f}")
        st.caption(f"With received commission **${payroll_paid_val:,.2f}**")
    col2.metric("Other Expense", f"${total_expense:,.2f}")
    col3.metric("Expected Commission to be Received", f"${expect_commission:,.2f}")
    col4.metric("Unknown Status", f"{int(unknown_commssion)}")

    col1, col2,col3,col4 = st.columns(4)
    with col1:
        st.metric("Realized Net Income", f"${realized_NI:,.2f}")
        st.caption(f"With Unpaid commission **${payroll_pending_received_val*0.15:,.2f}**")
    col2.metric("Expected Net Income", f"${expected_NI:,.2f}")
    col3.metric("Total Net Income - Estimated", f"${total_NI:,.2f}")
    col4.metric("Net Income per room", f"${NI_per_room:,.2f}")
    st.markdown("### 🏘️ Pending Received by Apartment")
    
    if count_unreceived > 0:
        apt_summary = df_unreceived.groupby('Apartment').agg(
            Count=('Apartment', 'size'),                  # 统计行数
            Pending_Received=('Commission', 'sum'),       # 注意：变量名中间用下划线，不能用空格
            Unknown=('Commission', lambda x: (pd.to_numeric(x) == 0).sum()) # 统计金额为 0 的记录
        ).reset_index()
    
        # 在 Streamlit 展示
        st.dataframe(
            apt_summary,
            column_config={
                "Apartment": "Apartment Name",
                "Count": "Total Records",
                "Pending_Received": st.column_config.NumberColumn("Pending Total", format="$%,.2f"),
                "Unknown": st.column_config.NumberColumn("Missing Info", format="%d")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.write("目前没有待收记录。")

    
    
    
