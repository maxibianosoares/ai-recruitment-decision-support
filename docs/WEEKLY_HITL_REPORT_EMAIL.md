# Laporan mingguan Human-in-the-Loop lewat email (otomatis)

Setiap Senin, sistem mengirim email berisi angka ringkas (tanpa nama, email
pelamar, atau alasan keputusan) ke administrator. Alamat penerima disimpan di
**variabel Railway**, bukan di kode (repo ini publik).

## Perintah
    python manage.py send_weekly_hitl_report --dry-run     # lihat isinya, tidak mengirim
    python manage.py send_weekly_hitl_report               # kirim laporan minggu terakhir yang selesai
    python manage.py send_weekly_hitl_report --force       # kirim ulang
    python manage.py send_weekly_hitl_report --to a@b.org  # ganti penerima untuk sekali jalan
    python manage.py send_weekly_hitl_report --lang id     # label Bahasa Indonesia

- Aman dijadwalkan: untuk satu penerima dan satu minggu, email hanya dikirim
  **sekali**. Bila jadwal terpicu dua kali atau perintah dijalankan ulang, jalan
  kedua dilewati ("already sent"). Pengiriman yang gagal akan dicoba lagi.
- Bila ada pengiriman gagal, perintah berakhir dengan kode error sehingga
  terlihat gagal di Railway.
- Pengiriman memakai Brevo yang sudah ada dan tercatat di `EmailLog`
  (Django Admin).

## Memasang jadwal di Railway (service terpisah)
Jadwal Railway memakai UTC dan prosesnya harus berhenti sendiri
([dokumentasi](https://docs.railway.com/cron-jobs)). Perintah ini berhenti
setelah selesai.

1. Di proyek Railway, buat **service baru dari repo GitHub yang sama**
   (jangan ubah service web dan worker yang sudah ada).
2. *Settings → Deploy → Custom Start Command*:
       python manage.py send_weekly_hitl_report
   (tanpa `migrate`; migrasi tetap dijalankan oleh service web.)
3. *Settings → Cron Schedule*: `0 0 * * 1`
   = Senin 00:00 UTC = Senin 09:00 waktu Timor-Leste/Korea (UTC+9).
   Laporan mencakup minggu Senin–Minggu yang baru selesai (zona waktu
   Django `TIME_ZONE`, bawaan Asia/Dili).
4. *Variables* pada service baru: salin variabel yang sama dengan service web
   (database, `SECRET_KEY`, `EMAIL_BACKEND`, `BREVO_API_KEY`,
   `DEFAULT_FROM_EMAIL`, dan lainnya), lalu tambahkan:
       HITL_REPORT_RECIPIENTS=portalvagascfp@gmail.com
   Beberapa penerima dipisah koma.
5. Uji sebelum menunggu hari Senin: di laptop jalankan `--dry-run` untuk melihat
   isi email. Untuk uji kirim nyata, ubah Cron Schedule sementara menjadi
   beberapa menit ke depan (jarak minimal 5 menit), lihat log service, lalu
   kembalikan ke `0 0 * * 1`. Dokumentasi Railway juga menyebut `railway cron
   run` untuk memicu manual; belum saya coba di akun Anda.

## Bila email tidak muncul
- Cek *Railway → service laporan → Logs*: "Sent to ...", "Skipped ...", atau
  "FAILED ...".
- Cek `EmailLog` di Django Admin (status sent/failed). "sent" berarti Brevo
  menerima, belum tentu masuk inbox. Periksa folder spam; pengirim harus
  alamat yang sudah diverifikasi di Brevo (`DEFAULT_FROM_EMAIL`).
- Jika `HITL_REPORT_RECIPIENTS` kosong, perintah berhenti dengan pesan
  "No recipient".
