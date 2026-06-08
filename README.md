# 👾 Pixel Trader Agent

แดชบอร์ดร่อนหุ้น/คริปโต/ทอง สไตล์ pixel agent — ฟรี ไม่ใช้ API key
ข้อมูลจาก Yahoo Finance

## ฟีเจอร์
- 🔎 ร่อนหาหุ้นหลายตลาด (US / ไทย / คริปโต / ทอง) ตามสไตล์ (สมดุล/เติบโต/มูลค่า/โมเมนตัม/ปันผล)
- 🔬 ดูรายตัว: ราคา + กราฟ + อินดิเคเตอร์ + ปัจจัยพื้นฐาน + ข่าว
- 🚀 ปุ่มวิเคราะห์เชิงลึก:
  - เปิดในเครื่องที่ล็อกอิน Claude Code → AI วิเคราะห์จริง (ฟรี)
  - เปิดบนคลาวด์ → สรุปอัตโนมัติจากตัวเลข (rule-based, ฟรี)

## รันในเครื่อง
```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy ฟรีบน Streamlit Community Cloud
1. push repo นี้ขึ้น GitHub (public)
2. ไปที่ https://share.streamlit.io → New app → เลือก repo นี้ → main file = `streamlit_app.py` → Deploy

⚠️ เพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน
