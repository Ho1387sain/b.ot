import threading
import requests
import pandas as pd
import jdatetime
from time import sleep
from flask import Flask, request
import os
import json

# ======== تنظیمات ========
TOKEN = "127184142:t8EC5x45a2aXInYYgz4L2EeVny7PBb1uiqwgeIpc"
API_URL = f"https://tapi.bale.ai/bot{TOKEN}"
BASE_URL = "https://b-ot.onrender.com"   # ✅ آدرس دپلوی روی Render
EXCEL_FILE = "data_fixed.xlsx"
ADMIN_NATIONAL_ID = "3861804190"          # ✅ کد ملی مدیر

app = Flask(__name__)

# ================== Flask Routes ==================
@app.route("/")
def home():
    return "✅ ربات شهریه‌یار فعال است و آماده دریافت پرداخت‌هاست."


@app.route("/callback")
def callback():
    chat_id = request.args.get("chat_id")
    amount_rial = int(request.args.get("amount", 0))
    national_id = request.args.get("id").strip()
    name = request.args.get("name")
    status = request.args.get("Status")

    amount_toman = amount_rial // 10  # ریال → تومان

    if status == "OK":
        try:
            sheets = pd.read_excel(EXCEL_FILE, sheet_name=None)

            df_students = sheets["دانشجویان"]
            df_students["کد ملی"] = df_students["کد ملی"].astype(str).str.strip()

            df_payments = sheets.get("پرداخت‌ها", pd.DataFrame(columns=["تاریخ", "نام", "مبلغ (تومان)", "وضعیت", "کد ملی"]))

            # ثبت پرداخت
            shamsi_date = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
            new_row = {
                "تاریخ": shamsi_date,
                "نام": name,
                "مبلغ (تومان)": amount_toman,
                "وضعیت": "موفق",
                "کد ملی": national_id
            }
            df_payments = pd.concat([df_payments, pd.DataFrame([new_row])], ignore_index=True)

            # کم کردن شهریه
            idx = df_students[df_students["کد ملی"] == national_id].index
            if not idx.empty:
                current_tuition = int(df_students.loc[idx[0], "شهریه"])
                new_tuition = max(0, current_tuition - amount_toman)
                df_students.loc[idx[0], "شهریه"] = new_tuition
            else:
                new_tuition = "نامشخص"

            # ذخیره در اکسل
            with pd.ExcelWriter(EXCEL_FILE, mode="w") as writer:
                df_students.to_excel(writer, sheet_name="دانشجویان", index=False)
                df_payments.to_excel(writer, sheet_name="پرداخت‌ها", index=False)

            # پیام به ربات
            msg = f"✅ پرداخت {amount_toman} تومان ثبت شد.\nباقی‌مانده شهریه: {new_tuition} تومان"
            requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": msg})

            # HTML به کاربر
            return f"""
            <html>
              <head><meta charset="utf-8"></head>
              <body style="font-family:Tahoma; text-align:center; margin-top:50px;">
                <h2 style="color:green;">✅ پرداخت با موفقیت انجام شد</h2>
                <p>مبلغ: {amount_toman} تومان</p>
                <p>شهریه باقی‌مانده: {new_tuition}</p>
                <p>نتیجه پرداخت در ربات هم ارسال شد.</p>
              </body>
            </html>
            """
        except Exception as e:
            print("خطا در callback:", e)
            return "Error", 500

    else:
        msg = "❌ پرداخت لغو شد یا ناموفق بود."
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": msg})

        return """
        <html>
          <head><meta charset="utf-8"></head>
          <body style="font-family:Tahoma; text-align:center; margin-top:50px;">
            <h2 style="color:red;">❌ پرداخت لغو شد یا ناموفق بود</h2>
            <p>لطفاً دوباره تلاش کنید.</p>
          </body>
        </html>
        """


# ================== Bot Logic ==================
def create_test_payment(amount, description, callback_url):
    url = "https://sandbox.zarinpal.com/pg/v4/payment/request.json"
    data = {
        "merchant_id": "00000000-0000-0000-0000-000000000000",
        "amount": amount,
        "description": description,
        "callback_url": callback_url
    }
    try:
        res = requests.post(url, json=data).json()
        if res.get("data") and res["data"].get("authority"):
            authority = res["data"]["authority"]
            return f"https://sandbox.zarinpal.com/pg/StartPay/{authority}", authority
    except Exception as e:
        print("خطا در ایجاد لینک پرداخت:", e)
    return None, None


def run_bot():
    last_update_id = None
    user_states = {}

    print("🤖 ربات فعال شد و در حال گوش دادن است...")

    while True:
        try:
            res = requests.get(f"{API_URL}/getUpdates", params={"offset": last_update_id}, timeout=10)
            data = res.json()

            if "result" in data:
                for update in data["result"]:
                    update_id = update["update_id"]

                    if last_update_id is None or update_id >= last_update_id:
                        last_update_id = update_id + 1

                        # پیام متنی
                        if "message" in update:
                            chat_id = update["message"]["chat"]["id"]
                            text = update["message"].get("text", "").strip()
                            print(f"پیام از {chat_id}: {text}")

                            # شروع
                            if text == "/start":
                                msg = "سلام! لطفاً کد ملی خود را وارد کنید."
                                user_states[chat_id] = {"step": "waiting_national_id"}
                                requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": msg})

                            # دریافت کد ملی
                            elif user_states.get(chat_id, {}).get("step") == "waiting_national_id" and text.isdigit():
                                national_id = text.strip()
                                sheets = pd.read_excel(EXCEL_FILE, sheet_name=None)

                                # ✅ حالت مدیر
                                if national_id == ADMIN_NATIONAL_ID:
                                    df_students = sheets["دانشجویان"]
                                    df_payments = sheets.get("پرداخت‌ها", pd.DataFrame())

                                    now = jdatetime.datetime.now()
                                    this_month = now.strftime("%Y/%m")

                                    df_month = df_payments[df_payments["تاریخ"].astype(str).str.startswith(this_month)]

                                    total_paid = df_month[df_month["وضعیت"] == "موفق"]["مبلغ (تومان)"].sum()
                                    count_paid = len(df_month[df_month["وضعیت"] == "موفق"])
                                    total_tuition_remain = df_students["شهریه"].sum()

                                    msg = (
                                        f"📊 گزارش ماه {this_month}\n"
                                        f"🔹 مجموع پرداخت‌های موفق: {total_paid} تومان\n"
                                        f"🔹 تعداد پرداخت‌های موفق: {count_paid}\n"
                                        f"🔹 مانده‌ی کل شهریه: {total_tuition_remain} تومان\n\n"
                                        "📜 ریز پرداخت‌های این ماه:\n"
                                    )

                                    for i, row in df_month.iterrows():
                                        msg += f"- {row['نام']} | {row['تاریخ']} | {row['مبلغ (تومان)']} تومان | {row['وضعیت']}\n"

                                    # ارسال گزارش متنی
                                    requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": msg})

                                    # ساخت و ارسال فایل اکسل
                                    report_file = "گزارش-ماه.xlsx"
                                    with pd.ExcelWriter(report_file, engine="openpyxl") as writer:
                                        df_month.to_excel(writer, sheet_name="ریز پرداخت‌ها", index=False)
                                        df_students.to_excel(writer, sheet_name="شهریه فعلی", index=False)

                                    files = {"document": open(report_file, "rb")}
                                    requests.post(
                                        f"{API_URL}/sendDocument",
                                        data={"chat_id": chat_id},
                                        files=files
                                    )

                                    # ✅ مدیر تموم شد → برگردیم
                                    user_states[chat_id] = {"step": None, "id": national_id, "name": "مدیر"}
                                    continue

                                # ✅ حالت دانشجو
                                df_students = sheets["دانشجویان"]
                                df_students["کد ملی"] = df_students["کد ملی"].astype(str).str.strip()

                                row = df_students[df_students["کد ملی"] == national_id]
                                if not row.empty:
                                    name = row.iloc[0]["نام"]
                                    tuition = int(row.iloc[0]["شهریه"])

                                    user_states[chat_id] = {"step": None, "id": national_id, "name": name}

                                    if tuition == 0:
                                        reply = f"کد ملی: {national_id}\nنام: {name}\n🎉 شهریه شما تسویه شده است!"
                                        buttons = [[{"text": "📜 ریز پرداخت‌ها", "callback_data": "show_payments"}]]
                                    else:
                                        reply = f"کد ملی: {national_id}\nنام: {name}\nمبلغ شهریه: {tuition} تومان"
                                        user_states[chat_id]["step"] = "choose_action"
                                        buttons = [[{"text": "📜 ریز پرداخت‌ها", "callback_data": "show_payments"},
                                                    {"text": "💳 پرداخت", "callback_data": "pay"}]]

                                    reply_markup = {"inline_keyboard": buttons}
                                    requests.post(f"{API_URL}/sendMessage", json={
                                        "chat_id": chat_id,
                                        "text": reply,
                                        "reply_markup": json.dumps(reply_markup, ensure_ascii=False)
                                    })
                                else:
                                    reply = "کد ملی شما یافت نشد!"
                                    requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": reply})

                            # ✅ دریافت مبلغ پرداختی
                            elif user_states.get(chat_id, {}).get("step") == "waiting_amount" and text.isdigit():
                                amount_rial = int(text)
                                name = user_states[chat_id]["name"]
                                national_id = user_states[chat_id]["id"]

                                callback_url = f"{BASE_URL}/callback?chat_id={chat_id}&amount={amount_rial}&id={national_id}&name={name}"
                                payment_url, authority = create_test_payment(amount_rial, f"پرداخت شهریه توسط {name}", callback_url)

                                if payment_url:
                                    msg = f"💳 لینک پرداخت شما:\n{payment_url}"
                                else:
                                    msg = "⚠️ خطا در ایجاد لینک پرداخت."
                                requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": msg})
                                user_states[chat_id]["step"] = None

                        # دکمه‌های اینلاین (بدون تغییر)
                        if "callback_query" in update:
                            cq = update["callback_query"]
                            cq_data = cq["data"]
                            cq_chat_id = cq["message"]["chat"]["id"]

                            try:
                                requests.post(f"{API_URL}/answerCallbackQuery", json={"callback_query_id": cq["id"]})
                            except Exception as e:
                                print("خطا در answerCallbackQuery:", e)

                            national_id = user_states.get(cq_chat_id, {}).get("id")
                            user_name = user_states.get(cq_chat_id, {}).get("name")

                            if cq_data == "show_payments":
                                if not national_id and not user_name:
                                    msg = "⚠️ لطفاً دوباره کد ملی خود را وارد کنید."
                                else:
                                    sheets = pd.read_excel(EXCEL_FILE, sheet_name=None)
                                    df_payments = sheets.get("پرداخت‌ها", pd.DataFrame())

                                    if "کد ملی" in df_payments.columns and df_payments["کد ملی"].notna().any():
                                        df_user_payments = df_payments[df_payments["کد ملی"].astype(str).str.strip() == str(national_id)]
                                    else:
                                        df_user_payments = df_payments[df_payments["نام"].astype(str).str.strip() == str(user_name)]

                                    if df_user_payments.empty:
                                        msg = "هیچ پرداختی برای شما ثبت نشده است."
                                    else:
                                        msg = "📜 ریز پرداخت‌های شما:\n\n"
                                        for i, (_, row) in enumerate(df_user_payments.iterrows(), start=1):
                                            status = str(row.get("وضعیت", "")).strip()
                                            if status == "موفق":
                                                status_icon = "✅"
                                            elif status == "ناموفق":
                                                status_icon = "❌"
                                            else:
                                                status_icon = "⏳"
                                            amount = row.get("مبلغ (تومان)", "")
                                            try:
                                                amount_str = f"{int(amount)}"
                                            except:
                                                amount_str = str(amount) if pd.notna(amount) else "نامشخص"
                                            msg += f"{i}️⃣ {row.get('تاریخ','نامشخص')} → {amount_str} تومان {status_icon} {status}\n"

                                requests.post(f"{API_URL}/sendMessage", json={"chat_id": cq_chat_id, "text": msg})
                                if cq_chat_id in user_states:
                                    user_states[cq_chat_id]["step"] = None

                            elif cq_data == "pay":
                                if cq_chat_id not in user_states or "id" not in user_states[cq_chat_id]:
                                    msg = "⚠️ لطفاً دوباره کد ملی خود را وارد کنید."
                                else:
                                    uid = user_states[cq_chat_id]["id"]
                                    sheets = pd.read_excel(EXCEL_FILE, sheet_name=None)
                                    df_students = sheets["دانشجویان"]
                                    df_students["کد ملی"] = df_students["کد ملی"].astype(str).str.strip()
                                    row = df_students[df_students["کد ملی"] == uid]
                                    if row.empty:
                                        msg = "⚠️ دانشجو یافت نشد. لطفاً دوباره کد ملی را ارسال کنید."
                                    else:
                                        tuition = int(row.iloc[0]["شهریه"])
                                        if tuition <= 0:
                                            msg = "💡 شهریه شما قبلاً تسویه شده است؛ نیازی به پرداخت نیست."
                                        else:
                                            user_states[cq_chat_id]["step"] = "waiting_amount"
                                            msg = "لطفاً مبلغ پرداختی خود را به ریال وارد کنید:"
                                requests.post(f"{API_URL}/sendMessage", json={"chat_id": cq_chat_id, "text": msg})

            sleep(2)
        except Exception as e:
            print("خطا در ربات:", e)
            sleep(5)


# ================== Run ==================
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
