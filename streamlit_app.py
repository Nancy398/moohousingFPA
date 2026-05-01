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
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
from dateutil.relativedelta import relativedelta
import plotly.express as px

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
            (self.df_expense, ['Commission', 'Expense'])
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
            
            # 费用过滤逻辑
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
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(st.secrets["GOOGLE_APPLICATION_CREDENTIALS"], scopes=scope)
        gc = gspread.authorize(credentials)
        worksheet = gc.open(name).worksheet(sheet)
        rows = worksheet.get_all_values()
        raw_df = pd.DataFrame(rows)
        if raw_df.empty: return raw_df
        
        new_header = raw_df.iloc[header_row].str.strip().tolist()
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
                
        df = pd.DataFrame(raw_df.values[header_row + 1:], columns=final_header)
        return df.dropna(how='all').reset_index(drop=True)
    
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
    df_2026 = read_file("Apartment Referral List", "2026", header_row=1)
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
    
    # D. 模式切换与模型实例化
    if show_total:
        df_input = pd.concat([df_2025, df_2026], ignore_index=True)
        model = FinancialModel(df_input, df_expense_raw, is_total=True)
        title_label = "All-Time History"
    else:
        df_input = df_2025 if select_year == 2025 else df_2026
        model = FinancialModel(df_input, df_expense_raw, select_year=select_year, is_total=False)
        title_label = f"Year {select_year}"
    
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
    
    # F. 现金流预测图表
    st.markdown("### 🏘️ Commission Cash In Map(Monthly)")
    
    now = datetime.datetime.now()
    today = pd.to_datetime(now.date())
    next_month_str = (now + relativedelta(months=1)).strftime('%Y-%m')
    def classify_full_status(row):
        if row['Received'] == "TRUE":
            # 优先使用 Receive date，如果没有则转为 pd.NaT
            r_date = pd.to_datetime(row['Receive date'], errors='coerce')
            if pd.notna(r_date):
                return r_date.strftime('%Y-%m'), "✅ Received"
            else:
                return "Unknown", "✅ Received"
        row['Predicted_Date'] = apply_prediction(row)
        pred_date = pd.to_datetime(row['Predicted_Date'], errors='coerce')
        
        if pd.isna(pred_date) or pred_date < today:
            # 已逾期：归入下个月
            return next_month_str, "⚠️ Slower than Expected"
        else:
            # 正常未来预期
            return pred_date.strftime('%Y-%m'), "📅 Future Expected"
    
    filter_year = str(select_year) if not show_total else None
    
    # 2. 应用分类逻辑（同上一步）
    plot_df = model.df_curr.copy()
    plot_df[['Forecast_Month', 'Category']] = plot_df.apply(
        lambda x: pd.Series(classify_full_status(x)), axis=1
    )
    
    # 3. 过滤掉无法识别月份的数据
    plot_df = plot_df[plot_df['Forecast_Month'] != "Unknown"]
    
    # --- 关键修改点：如果是单年模式，过滤掉非本年的数据 ---
    if filter_year:
        # 只保留月份字符串以该年份开头的行 (例如 "2026-01" 匹配 "2026")
        plot_df = plot_df[plot_df['Forecast_Month'].str.startswith(filter_year)]
    
    # 4. 聚合数据
    if not plot_df.empty:
        plot_data = plot_df.groupby(['Forecast_Month', 'Category'])['Commission'].sum().reset_index()
        
        # 确保月份排序（Plotly 默认按字符串排序 YYYY-MM 正好符合时间顺序）
        plot_data = plot_data.sort_values(['Forecast_Month', 'Category'])
    
        # 5. 绘图
        fig = px.bar(
            plot_data, 
            x='Forecast_Month', 
            y='Commission', 
            color='Category',
            color_discrete_map={
                "✅ Received": "#A2D9A2",     
                "📅 Future Expected": "#AED6F1",      
                "⚠️ Slower than Expected": "#F5B7B1"  
            },
            text_auto=',.0f', 
            barmode='stack',
            title=f"📊 {title_label} 佣金月度看板"
        )
    
        # 优化 X 轴显示，强制显示 12 个月（即使某个月没数据也能空出来占位，更美观）
        if filter_year:
            all_months = [f"{filter_year}-{m:02d}" for m in range(1, 13)]
            fig.update_xaxes(tickvals=all_months, ticktext=all_months)
    
        fig.update_traces(textposition='inside', textfont=dict(color="black", size=10))
        fig.update_layout(
            xaxis_title="Month",
            yaxis_title="Amount ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"💡 {title_label} 暂无相关月份的佣金数据。")

    
    # G. 公寓明细表
    st.markdown("### 🏘️ Pending Received by Apartment")
    df_pending_table = plot_df[plot_df['Category'] != "✅ Received"].copy()

    if not df_pending_table.empty:
        # 2. 聚合计算
        apt_summary = df_pending_table.groupby('Apartment').agg(
            Count=('Apartment', 'size'),
            Pending_Total=('Commission', 'sum'),
            # 统计那些状态是已入住但 Commission 填了 0 的，或者是还没填金额的
            Missing_Info=('Commission', lambda x: (pd.to_numeric(x) == 0).sum())
        ).reset_index().sort_values('Pending_Total', ascending=False)
    
        # 3. 渲染表格
        st.dataframe(
            apt_summary,
            column_config={
                "Apartment": "Apartment Name",
                "Count": "Unpaid Units",
                "Pending_Total": st.column_config.NumberColumn("Pending Amount", format="$%,.0f"),
                "Missing_Info": st.column_config.NumberColumn("Missing $ Data", format="%d")
            },
            hide_index=True, 
            use_container_width=True
        )
        
        # 可选：加一个提示，告诉用户这些钱的总额
        total_p = apt_summary['Pending_Total'].sum()
        st.caption(f"☝️ 以上公寓共有 **{len(apt_summary)}** 处待收，总计金额约 **${total_p:,.0f}**")
    
    else:
        st.success(f"🎉 恭喜！{display_title} 所有款项已结清，没有待收项目。")
            
        
