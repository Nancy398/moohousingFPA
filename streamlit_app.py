import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go 
import plotly.express as px
# from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
import gspread
import datetime
from gspread_dataframe import set_with_dataframe
from dateutil.relativedelta import relativedelta

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

# ==========================================
# 1. 核心财务逻辑类 (FinancialModel)
# ==========================================
with tab_apartments:
    class FinancialModel:
        def __init__(self, df_referral, df_expense, select_year=None, is_total=False):
            self.df_curr = df_referral.copy()
            self.df_expense = df_expense.copy()
            self.select_year = str(select_year) if select_year else None
            self.is_total = is_total
            
            # 自动执行清洗与计算
            self._clean_data()
            self._calculate_metrics()
    
        def _clean_data(self):
            """统一处理金额格式转换"""
            items_to_fix = [
            (self.df_curr, ['Received Commission', 'Bonus to resident', 'Commission']),
            (self.df_expense, ['Commission', 'Expense','Cashflow'])
        ]
        
            for df, columns in items_to_fix:
                for col in columns:
                    if col in df.columns:
                        df[col] = (
                            df[col].astype(str)
                            .str.replace(r'[¥$,]', '', regex=True)
                            .replace('nan', '0')
                        )
                        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
        def _calculate_metrics(self):
            """核心指标计算逻辑"""
            df = self.df_curr
            dfe = self.df_expense
            
            if not self.is_total and self.select_year:
                dfe_filtered = dfe[dfe['Year'].astype(str) == self.select_year]
            else:
                dfe_filtered = dfe
    
            # 1. 收入类
            self.total_received_comm = df.loc[df['Received'] == 'TRUE', 'Received Commission'].sum()
            self.expect_commission = df.loc[df['Received'] == 'FALSE', 'Commission'].sum()
            
            # 2. 支出类
            self.paid_comm_curr = dfe_filtered['Commission'].sum()
            self.other_expense_curr = dfe_filtered['Expense'].sum()
            self.exp_quarter =  dfe_filtered['Season']
            self.exp_cashflow = dfe_filtered['Cashflow'].sum()
            self.bonus_residents_curr = df['Bonus to resident'].sum()
            self.total_expense = self.other_expense_curr + self.bonus_residents_curr
            
            # 3. 提成与工资逻辑
            # 计算已回款但尚未支付 15% 提成的金额
            self.payroll_pending_val = df[(df['Payroll'] == 'FALSE') & (df['Received'] == 'TRUE')]['Received Commission'].sum()
            self.payroll_paid_val = df[(df['Payroll'] == 'TRUE') & (df['Received'] == 'TRUE')]['Received Commission'].sum()
            
            # 4. 状态统计
            self.checked_in_count = len(df[df['状态'] == '已入住'])
            self.count_unreceived = len(df[(df['状态'] == '已入住') & (df['Received'] == 'FALSE')])
            self.received_count = self.checked_in_count - self.count_unreceived
            
            # 5. 利润计算 (Net Income)
            # Realized NI = 已收佣金 - (其他支出 + 住户返现) - 已付中介佣金 - (已回款待付的15%工资提成)
            self.realized_NI = self.total_received_comm - self.total_expense - self.paid_comm_curr - (self.payroll_pending_val * 0.15)
            # Expected NI = 待收佣金 * 85% (扣除预计15%提成)
            self.expected_NI = self.expect_commission * 0.85
            self.total_NI = self.realized_NI + self.expected_NI
            
            # 6. 单房利润
            self.NI_per_room = self.realized_NI / self.checked_in_count if self.checked_in_count > 0 else 0
    
    # ==========================================
    # 2. 数据读取与预测函数
    # ==========================================
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
        df_all_history = pd.concat(df_list, ignore_index=True)
        df_all_history['Move-in Date'] = pd.to_datetime(df_all_history['入住时间'], errors='coerce')
        df_all_history['Received Date'] = pd.to_datetime(df_all_history['Receive date'], errors='coerce')
        
        paid_mask = (df_all_history['Received'] == "TRUE") & df_all_history['Move-in Date'].notna() & df_all_history['Received Date'].notna()
        history_paid = df_all_history[paid_mask].copy()
        history_paid['days'] = (history_paid['Received Date'] - history_paid['Move-in Date']).dt.days
        
        dso_map = history_paid.groupby('Apartment')['days'].mean().to_dict()
        global_avg = history_paid['days'].mean() if not history_paid.empty else 45
        return dso_map, global_avg
    
    # ==========================================
    # 3. Streamlit UI 布局
    # ==========================================
    st.set_page_config(layout="wide", page_title="Apartment Financial Dashboard")
    
    # A. 加载原始数据
    df_2025 = read_file("Apartment Referral List", "2025", header_row=1)
    df_2025['Year'] = '2025'
    df_2026 = read_file("Apartment Referral List", "2026", header_row=1)
    df_2026['Year'] = '2026'
    df_expense_raw = read_file("Apartments FA", "Expense")
    
    # B. 计算回款预测映射
    dso_map, global_avg = get_dynamic_dso([df_2025, df_2026])
    
    def apply_prediction(row):
        if row['Received'] == "TRUE": return row['Receive date']
        move_in = pd.to_datetime(row['入住时间'], errors='coerce')
        if pd.isna(move_in): return None
        avg_days = dso_map.get(row['Apartment'], global_avg)
        return move_in + pd.Timedelta(days=int(avg_days))
    
    # C. 顶部控制栏
    with st.container():
        c_left, c_right = st.columns([0.7, 0.3], vertical_alignment="bottom")
        with c_left:
            select_year = st.segmented_control("Year Selection", options=[2025, 2026], default=2026, label_visibility="collapsed")
        with c_right:
            show_total = st.toggle("📊 Show All-Time Total View", value=False)
            comparison_mode = st.toggle("🔄 Comparison Mode", value=False, disabled=show_total)
    
    # D. 模式切换与模型实例化
    if show_total:
        df_input = pd.concat([df_2025, df_2026], ignore_index=True)
        model = FinancialModel(df_input, df_expense_raw, is_total=True)
        title_label = "All-Time History"
        st.session_state.view_mode = 'Standard'
    elif comparison_mode:
        selected_years = st.multiselect(
                "选择对比年份", 
                options=[2025, 2026], 
                default=[2025, 2026]
            )
        if not selected_years:
            st.warning("At Least Select One.")
            st.stop()
        compare_dfs = []
        if 2025 in selected_years: compare_dfs.append(df_2025)
        if 2026 in selected_years: compare_dfs.append(df_2026)
        df_input = pd.concat(compare_dfs, ignore_index=True)
        # 对比模式通常涉及多年，is_total 设为 True 以处理跨年支出
        model = FinancialModel(df_input, df_expense_raw, is_total=True)
        title_label = "Comparison View"
        st.session_state.view_mode = 'Comparison'
    else:
        df_input = df_2025 if select_year == 2025 else df_2026
        model = FinancialModel(df_input, df_expense_raw, select_year=select_year, is_total=False)
        title_label = f"Year {select_year}"
        st.session_state.view_mode = 'Standard'
    if st.session_state.view_mode == 'Standard':
        # E. 渲染 Dashboard 指标
        st.title(f"📊 {title_label} Analysis")
        st.divider()
        
        # 第一行：基础统计
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("已入住总数", f"{model.checked_in_count}")
        m2.metric("已收数", f"{model.received_count}")
        m3.metric("待收数", f"{model.count_unreceived}")
        m4.metric("Already Received", f"${model.total_received_comm:,.2f}")
        
        # 第二行：费用与待收
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Paid Commission", f"${model.paid_comm_curr:,.2f}")
            st.caption(f"With received commission: **${model.payroll_paid_val:,.2f}**")
        m2.metric("Total Expense", f"${model.total_expense:,.2f}")
        m3.metric("Expected Commission", f"${model.expect_commission:,.2f}")
        # 计算未知金额的单数
        unknown_count = len(model.df_curr[(model.df_curr['Received'] == 'FALSE') & (model.df_curr['Commission'] == 0) & (model.df_curr['状态'] == '已入住')])
        m4.metric("Unknown Commission", f"{unknown_count}")
        
        # 第三行：利润分析
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Realized Net Income", f"${model.realized_NI:,.2f}")
            st.caption(f"With unpaid 15% Comm: **${model.payroll_pending_val * 0.15:,.2f}**")
        m2.metric("Expected Net Income", f"${model.expected_NI:,.2f}")
        m3.metric("Estimated Total NI", f"${model.total_NI:,.2f}")
        m4.metric("NI per Room", f"${model.NI_per_room:,.2f}")
    
        def classify_full_status(row):
            if row['Received'] == "TRUE":
                r_date = pd.to_datetime(row['Receive date'], errors='coerce')
                if pd.notna(r_date):
                    return r_date.strftime('%Y-%m'), "✅ Received"
                else:
                    return "Unknown", "✅ Received"
            row['Predicted_Date'] = apply_prediction(row)
            pred_date = pd.to_datetime(row['Predicted_Date'], errors='coerce')
            if pd.isna(pred_date) or pred_date < today:
                return next_month_str, "⚠️ Slower than Expected"
            else:
                return pred_date.strftime('%Y-%m'), "📅 Future Expected"
    
        st.markdown("### 🏘️ Commission Cash In Map(Monthly)")
        col_btn1, col_btn2, col_btn3 = st.columns(3) 
        if 'view_mode' not in st.session_state:
            st.session_state.view_mode = 'Standard'
        with col_btn1:
            if st.button("📅 Standard (近一年)", use_container_width=True):
                st.session_state.view_mode = 'Standard'
        with col_btn2:
            if st.button("📊 Comparison", use_container_width=True):
                st.session_state.view_mode = 'Comparison'
        with col_btn3:
            if st.button("🚀 Projection", use_container_width=True):
                st.session_state.view_mode = 'Projection'
        
        st.divider()
        
        # --- 2. 基础数据准备 ---
        now = datetime.datetime.now()
        today = pd.to_datetime(now.date())
        next_month_str = (now + relativedelta(months=1)).strftime('%Y-%m')
        df_2025 = read_file("Apartment Referral List", "2025", header_row=1)
        df_2026 = read_file("Apartment Referral List", "2026", header_row=1)
        df_2025['Commission'] = (
            df_2025['Commission']
            .astype(str)
            .str.replace('$', '')
            .str.replace(',', '')
            .str.strip()
        )
        df_2025['Commission'] = pd.to_numeric(df_2025['Commission'], errors='coerce').fillna(0)
        df_2026['Commission'] = (
            df_2026['Commission']
            .astype(str)
            .str.replace('$', '')
            .str.replace(',', '')
            .str.strip()
        )
        df_2026['Commission'] = pd.to_numeric(df_2026['Commission'], errors='coerce').fillna(0)
        # 合并全量数据用于处理
        df_all_data = pd.concat([df_2025, df_2026], ignore_index=True)
        
        # 应用分类标签 (封装在前面讨论过的逻辑中)
        def get_processed_df(df):
            temp_df = df.copy()
            # 确保金额清洗已完成
            temp_df[['Forecast_Month', 'Category']] = temp_df.apply(
                lambda x: pd.Series(classify_full_status(x)), axis=1
            )
            return temp_df[temp_df['Forecast_Month'] != "Unknown"]
        
        # --- 3. 不同模式的界面展示 ---
        
        # ==========================================
        # 模式 A: Standard (近 12 个月滚动)
        # ==========================================
        if st.session_state.view_mode == 'Standard':
            plot_df = get_processed_df(df_all_data)
            plot_df['Temp_Date'] = pd.to_datetime(plot_df['Forecast_Month'] + "-01")
            one_year_ago = today.replace(day=1) - relativedelta(months=11)
            standard_df = plot_df[(plot_df['Temp_Date'] >= one_year_ago) & (plot_df['Temp_Date'] <= today.replace(day=1))]
            plot_data = standard_df.groupby(['Forecast_Month', 'Category'])['Commission'].sum().reset_index()
            fig = px.bar(
                plot_data, x='Forecast_Month', y='Commission', color='Category',
                color_discrete_map={"✅ Received": "#A2D9A2", "📅 Future Expected": "#AED6F1", "⚠️ Slower than Expected": "#F5B7B1"},
                text_auto=',.0f', barmode='stack'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # ==========================================
        # 模式 B: Comparison (折线图对比)
        # ==========================================
    elif st.session_state.view_mode == 'Comparison':
        st.markdown("### 🏆 年度核心指标综合对比 (Annual Summary)")

    # 1. 预计算所有指标的总量
        summary_data = {}
        for y in selected_years:
            y_df = model.df_curr[model.df_curr['Year'].astype(str) == str(y)].copy()
            ye_df = model.df_expense[model.df_expense['Year'].astype(str) == str(y)].copy()
    
            # 计算基础值
            rooms = len(y_df[y_df['状态'] == "已入住"])
            received = y_df[y_df['Received'] == "TRUE"]['Received Commission'].sum()
            pending = y_df[y_df['Received'] == "FALSE"]['Commission'].sum()
            
            # 净利计算逻辑 (权责发生制)
            bonus = y_df['Bonus to resident'].sum()
            payroll = received * 0.15
            fixed_exp = ye_df['Expense'].sum()
            net_income = received - bonus - payroll - fixed_exp
            
            # 效率计算
            ni_per_room = net_income / rooms if rooms > 0 else 0
    
            summary_data[str(y)] = {
                "Received Commission($)": [
                    {"Metric": "Received", "Value": received}
                    # {"Metric": "Pending", "Value": pending}
                ],
                "Moved in (Rooms)": [
                    {"Metric": "Rooms Count", "Value": rooms}
                ],
                "Realized Net Income ($)": [
                    {"Metric": "Net Income", "Value": net_income}
                ],
                "Efficiency (NI per Room)": [
                    {"Metric": "NI per Room", "Value": ni_per_room}
                ]
            }
    
        # 2. 创建 2x2 布局
        r1_c1, r1_c2, r1_c3,r1_c4 = st.columns(4)
        tiles = [
            (r1_c1, "Received Commission($)", "group"), # 这个图包含两个指标对比
            (r1_c2, "Moved in (Rooms)", "group"),
            (r1_c3, "Realized Net Income ($)", "group"),
            (r1_c4, "Efficiency (NI per Room)", "group")
        ]
    
        # 3. 循环绘图
        for col, title, b_mode in tiles:
            plot_list = []
            for y in selected_years:
                for item in summary_data[str(y)][title]:
                    plot_list.append({
                        "Year": str(y),
                        "Label": item["Metric"],
                        "Value": item["Value"]
                    })
            
            df_plot = pd.DataFrame(plot_list)
            df_plot['Year'] = df_plot['Year'].astype(str)
            # 绘图逻辑
            fig = px.bar(
                df_plot, 
                x='Year', # 第一个图按指标分，其他按年份分
                y='Value', 
                color='Year',
                barmode="group",
                text_auto=',.0f',
                title=title,
                color_discrete_map={"2025": "#AED6F1", "2026": "#2E86C1"},
                height=300
            )
            fig.update_xaxes(type='category')
            fig.update_traces(textposition='outside', cliponaxis=False)
            fig.update_layout(
                xaxis_title=None, yaxis_title=None,
                showlegend=False,
                margin=dict(l=20, r=20, t=40, b=20)
            )
            col.plotly_chart(fig, use_container_width=True)
    
        st.divider()
        st.markdown("### 📊 季度业绩走势对比")
        c1, c2= st.columns([0.5, 0.5])
        with c1:
            metrics_map = {
                "Realized Net Income": "Net_Income",
                "Actual Cash Flow": "Cash_Flow"
            }
            selected_label = st.selectbox("🎯 Select Metrics", options=list(metrics_map.keys()))
        
        with c2:
            # 让用户选择对比哪些季度（默认全选）
            selected_quarters = st.multiselect("📅 Select Season", options=[1, 2, 3, 4], default=[1, 2, 3, 4], format_func=lambda x: f"Q{x}")
    
        if not selected_quarters:
            st.warning("请至少选择一个季度进行对比")
            st.stop()
        compare_list = []

        for y in selected_years:
            # --- 数据预处理 ---
            y_df = model.df_curr[model.df_curr['Year'].astype(str) == str(y)].copy()
            ye_df = model.df_expense[model.df_expense['Year'].astype(str) == str(y)].copy()
    
            # 统一转换时间字段
            y_df['MoveIn_Q'] = pd.to_datetime(y_df['入住时间'], errors='coerce').dt.quarter
            y_df['Rec_Date'] = pd.to_datetime(y_df['Receive date'], errors='coerce')
            y_df['Rec_Q'] = y_df['Rec_Date'].dt.quarter
            
            # 支出表利用你新增的两列
            ye_df['Exp_Q'] = pd.to_numeric(ye_df['Season'], errors='coerce') 
            ye_df['CF_Q'] = pd.to_numeric(ye_df['Season'], errors='coerce').fillna(0).astype(int)
    
            # --- 2. 核心计算逻辑 ---
            if selected_label == "Realized Net Income":
                y_df_filtered = y_df[y_df['MoveIn_Q'].isin(selected_quarters)]
                ye_df_filtered = ye_df[ye_df['Exp_Q'].isin(selected_quarters)]
                rev = y_df_filtered[y_df_filtered['Received'] == "TRUE"].groupby('MoveIn_Q')['Received Commission'].sum()
                bonus = y_df_filtered.groupby('MoveIn_Q')['Bonus to resident'].sum()
                payroll = y_df_filtered[y_df_filtered['Received'] == "TRUE"].groupby('MoveIn_Q')['Received Commission'].sum() * 0.15
                fixed_exp = ye_df_filtered.groupby('Exp_Q')['Expense'].sum()
                q_series = rev.fillna(0) - bonus.fillna(0) - payroll.fillna(0) - fixed_exp.fillna(0)
    
            elif selected_label == "Actual Cash Flow":
                y_df_filtered = y_df[y_df['Rec_Q'].isin(selected_quarters)]
                ye_df_filtered = ye_df[ye_df['CF_Q'].isin(selected_quarters)]
                cash_in = y_df_filtered.groupby('Rec_Q')['Received Commission'].sum()
                cash_out = ye_df_filtered.groupby('CF_Q')['Cashflow'].sum()
                q_series = cash_in.fillna(0) - cash_out.fillna(0)
    
            # --- 3. 结果汇总 ---
            q_df = q_series.reset_index()
            q_df.columns = ['Quarter', 'Value']
            # 确保只显示选中的季度
            full_q = pd.DataFrame({'Quarter': selected_quarters})
            q_df = full_q.merge(q_df, on='Quarter', how='left').fillna(0)
            q_df['Year'] = str(y)
            q_df['Quarter_Label'] = q_df['Quarter'].apply(lambda x: f"Q{int(x)}")   
            compare_list.append(q_df)
    
        # --- 4. 绘图 ---
        if compare_list:
            plot_data = pd.concat(compare_list).sort_values(['Quarter', 'Year'])
            
            fig = px.bar(
                plot_data, x='Quarter_Label', y='Value', color='Year',
                barmode='group', text_auto=',.0f',
                title=f"📅 {selected_label} 年度季度对比",
                color_discrete_map={"2025": "#AED6F1", "2026": "#2E86C1"} # 不同深度的蓝色
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.markdown(f"### 📅 {', '.join(map(str, selected_years))} 年度季度全维度对比")
        is_cash_basis = st.toggle("💸Cashflow Basis", value=False)
    
    # 动态定义标签
        label_net = "Net Cashflow ($)" if is_cash_basis else "Realized Net Income ($)"
        label_ave = "Cashflow Per Unit ($)" if is_cash_basis else "Income Per Room ($)"
    
    # 1. 定义要对比的四个核心指标及其计算逻辑
        comp_metrics = {
            "Received Commission ($)": "Received",
            "Moved in (Rooms)": "Rooms",
            "Pending Commission ($)": "Pending",
            label_net: "Net",
            label_ave: "Ave"
        }
    
        # 2. 创建 2x2 布局
        row1_col1, row1_col2, row1_col3 = st.columns(3)
        row2_col1, row2_col2 = st.columns(2)
        chart_containers = [row1_col1, row1_col2,row1_col3, row2_col1, row2_col2]
    
        # 3. 循环计算并绘图
        for (label, key), container in zip(comp_metrics.items(), chart_containers):
            all_q_data = []
            
            for y in selected_years:
                # 提取数据
                y_df = model.df_curr[model.df_curr['Year'].astype(str) == str(y)].copy()
                ye_df = model.df_expense[model.df_expense['Year'].astype(str) == str(y)].copy()
    
                # 预处理季度
                y_df['MoveIn_Q'] = pd.to_datetime(y_df['入住时间'], errors='coerce').dt.quarter
                y_df['Rec_Q'] = pd.to_datetime(y_df['Receive date'], errors='coerce').dt.quarter
                ye_df['Season_Int'] = pd.to_numeric(ye_df['Season'], errors='coerce').fillna(0).astype(int)
    
                # --- 根据指标 key 计算季度序列 ---
                if key == "Received":
                    if is_cash_basis:
                        # 现金模式：按实际收到钱的季度聚合
                        q_series = y_df[y_df['Received'] == "TRUE"].groupby('Rec_Q')['Received Commission'].sum()
                    else:
                        # 权责模式：按入住季度统计已到账金额
                        q_series = y_df[y_df['Received'] == "TRUE"].groupby('MoveIn_Q')['Received Commission'].sum()
                
                elif key == "Rooms":
                    # 房间数始终按业务发生的入住时间算
                    temp_df = model.df_curr[model.df_curr['Year'].astype(str) == str(y)].copy()
                    temp_df['MoveIn_Q'] = pd.to_datetime(temp_df['入住时间'], errors='coerce').dt.quarter
                    q_series = temp_df[temp_df['状态'] == "已入住"].groupby('MoveIn_Q').size()
                
                elif key == "Pending":
                    temp_df = model.df_curr[model.df_curr['Year'].astype(str) == str(y)].copy()
                    temp_df['MoveIn_Q'] = pd.to_datetime(temp_df['入住时间'], errors='coerce').dt.quarter
                    q_series = temp_df[temp_df['Received'] == "FALSE"].groupby('MoveIn_Q')['Commission'].sum()
                
                elif key == "Net" or key == "Ave":
                    if is_cash_basis:
                        rev = y_df[y_df['Received'] == "TRUE"].groupby('Rec_Q')['Received Commission'].sum()
                        fixed_exp = ye_df.groupby('Season_Int')['Cashflow'].sum()
                        net_q = rev.fillna(0) - fixed_exp.fillna(0)
                    else:
                        rev = y_df[y_df['Received'] == "TRUE"].groupby('MoveIn_Q')['Received Commission'].sum()
                        bonus = y_df.groupby('MoveIn_Q')['Bonus to resident'].sum()
                        payroll = ye_df.groupby('Season_Int')['Commission'].sum()
                        fixed_exp = ye_df.groupby('Season_Int')['Expense'].sum()
                        net_q = rev.fillna(0) - bonus.fillna(0) - payroll.fillna(0) - fixed_exp.fillna(0)
                    if key == "Net":
                        q_series = net_q
                    else:
                        temp_df = model.df_curr[model.df_curr['Year'].astype(str) == str(y)].copy()
                        temp_df['MoveIn_Q'] = pd.to_datetime(temp_df['入住时间'], errors='coerce').dt.quarter
                        move_count = temp_df[temp_df['状态'] == "已入住"].groupby('MoveIn_Q').size()
                        q_series = net_q / move_count.replace(0, 1)
    
                # --- 补全数据并生成 Label ---
                q_df = q_series.reset_index()
                q_df.columns = ['Quarter', 'Value']
                q_df = pd.DataFrame({'Quarter': [1,2,3,4]}).merge(q_df, on='Quarter', how='left').fillna(0)
                q_df['Year'] = str(y)
                q_df['Quarter_Label'] = q_df['Quarter'].apply(lambda x: f"Q{int(x)}")
                all_q_data.append(q_df)
    
            # --- 绘图部分 (保持不变) ---
            if all_q_data:
                plot_df = pd.concat(all_q_data)
                fig_q = px.bar(plot_df, x='Quarter_Label', y='Value', color='Year', barmode='group', text_auto=',.0f',
                               title=label, color_discrete_map={"2025": "#AED6F1", "2026": "#2E86C1"}, height=320)
                fig_q.update_traces(textposition='outside', cliponaxis=False)
                fig_q.update_layout(xaxis=dict(type='category'), xaxis_title=None, yaxis_title=None, 
                                    showlegend=True if key == "Received" else False, margin=dict(l=10, r=10, t=40, b=10))
                container.plotly_chart(fig_q, use_container_width=True)

        st.markdown("---")
        st.markdown("### 📊 利润 vs 现金流：深度盈余质量分析")
        
        # 1. 准备数据
        ni_vs_cf_list = []
        
        for y in selected_years:
            y_df = model.df_curr[model.df_curr['Year'].astype(str) == str(y)].copy()
            ye_df = model.df_expense[model.df_expense['Year'].astype(str) == str(y)].copy()
            
            # --- 计算所需维度 ---
            y_df['MoveIn_Q'] = pd.to_datetime(y_df['入住时间'], errors='coerce').dt.quarter
            y_df['Rec_Q'] = pd.to_datetime(y_df['Receive date'], errors='coerce').dt.quarter
            ye_df['Season_Int'] = pd.to_numeric(ye_df['Season'], errors='coerce').fillna(0).astype(int)
            ye_df['CF_Month'] = pd.to_numeric(ye_df['Cashflow'], errors='coerce')
            ye_df['CF_Q'] = ((ye_df['CF_Month'] - 1) // 3 + 1).fillna(0).astype(int)
    
            for q in [1, 2, 3, 4]:
                # A. 计算该季度的 NI (权责发生制)
                # 收入看入住 Q，支出看 Season
                rev_ni = y_df[y_df['MoveIn_Q'] == q]['Received Commission'].sum()
                bonus_ni = y_df[y_df['MoveIn_Q'] == q]['Bonus to resident'].sum()
                payroll_ni = ye_df[ye_df['Season_Int'] == q]['Commission'].sum()
                exp_ni = ye_df[ye_df['Season_Int'] == q]['Expense'].sum()
                val_ni = rev_ni - bonus_ni - payroll_ni - exp_ni
                
                # B. 计算该季度的 Cash Flow (现金流口径)
                # 收入看回款 Q，支出看 CF_Q
                rev_cf = y_df[y_df['Rec_Q'] == q]['Received Commission'].sum()
                bonus_cf = y_df[y_df['Rec_Q'] == q]['Bonus to resident'].sum()
                exp_cf = ye_df[ye_df['CF_Q'] == q]['Cashflow'].sum()
                val_cf = rev_cf - bonus_cf - exp_cf
                
                ni_vs_cf_list.append({"Year": str(y), "Quarter": f"Q{q}", "Type": "Net Income", "Value": val_ni})
                ni_vs_cf_list.append({"Year": str(y), "Quarter": f"Q{q}", "Type": "Cash Flow", "Value": val_cf})
    
        # 2. 绘图
        df_compare = pd.DataFrame(ni_vs_cf_list)
        
        # 我们可以通过年份进行分面(Facet)，或者通过不同的颜色区分
        # 这里推荐使用多图并行，或者通过下拉框选择年份看对比
        for y_val in selected_years:
            df_year = df_compare[df_compare['Year'] == str(y_val)]
            
            fig_dual = px.bar(
                df_year, 
                x='Quarter', 
                y='Value', 
                color='Type',
                barmode='group',
                text_auto=',.0f',
                title=f"📅 {y_val}年度：利润 (NI) vs 现金流 (CF) 对比",
                # 利润用蓝色系，现金流用绿色系，对比更鲜明
                color_discrete_map={"Net Income": "#AED6F1", "Cash Flow": "#2E86C1"}
            )
            
            fig_dual.update_traces(textposition='outside', cliponaxis=False)
            fig_dual.update_layout(
                yaxis_title="Amount ($)",
                xaxis_title=None,
                legend_title=None,
                margin=dict(l=20, r=20, t=50, b=20)
            )
            
            st.plotly_chart(fig_dual, use_container_width=True)
            
    elif st.session_state.view_mode == 'Projection':
        plot_df = get_processed_df(df_all_data)
        plot_df['Temp_Date'] = pd.to_datetime(plot_df['Forecast_Month'] + "-01")
        
        # 过滤：只看今天及以后的数据
        projection_df = plot_df[plot_df['Temp_Date'] >= today.replace(day=1)]
        # 只看待收部分
        projection_df = projection_df[projection_df['Category'] != "✅ Received"]
        plot_data = projection_df.groupby(['Forecast_Month', 'Category'])['Commission'].sum().reset_index()
        fig_proj = px.bar(
            plot_data, x='Forecast_Month', y='Commission', color='Category',
            color_discrete_map={"📅 Future Expected": "#AED6F1", "⚠️ Slower than Expected": "#F5B7B1"},
            text_auto=',.0f', barmode='stack' # 使用 group 模式让对比更明显
        )
        fig_proj.update_traces(
            textposition='inside', 
            textfont=dict(color="black", size=11),
            insidetextanchor='middle'
        )
        
        fig_proj.update_layout(
            xaxis_title="Month (Predicted)",
            yaxis_title="Pending Amount ($)",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        st.plotly_chart(fig_proj, use_container_width=True)
        
        # 6. 额外补充：预测总额小计
        total_projected = projection_df['Commission'].sum()
        overdue_projected = projection_df[projection_df['Category'] == "⚠️ Slower than Expected"]['Commission'].sum()
        
        c1, c2 = st.columns(2)
        c1.metric("未来待收总额", f"${total_projected:,.2f}")
        c2.metric("其中已逾期/顺延", f"${overdue_projected:,.2f}", delta=f"{(overdue_projected/total_projected)*100:.1f}% of total", delta_color="inverse")
        
    else:
        st.info("💡 目前没有未来的待收记录。")
    
  
