# Pemantau pipeline (email ke admin)

Perintah `python manage.py monitor_pipeline` memeriksa antrean pemrosesan AI
dan lamaran yang menunggu keputusan panitia. Ia hanya menghitung (tanpa AI,
tanpa nama pelamar), lalu mengirim email ke admin.

## Kapan email dikirim

| Email | Kapan |
|---|---|
| `[Pipeline Alert] ...` | Hanya saat ada masalah: antrean tertahan, lamaran macet, atau ada kegagalan AI dalam 24 jam. Alert yang sama tidak dikirim ulang selama 6 jam kecuali angkanya berubah. |
| `[Pipeline Daily Summary] <tanggal>` | Satu kali per hari, pada run pertama setelah jam 09:00 waktu lokal (Asia/Dili), walau semuanya normal. |

CV yang tidak terbaca (`DOCUMENT_INVALID` / `EXTRACTION_FAILED`) hanya muncul
sebagai informasi di ringkasan harian, karena kandidat bisa mengunggah ulang.
Lamaran yang menunggu keputusan lebih dari 14 hari muncul sebagai catatan di
ringkasan harian.

## Mencoba di komputer sendiri

```powershell
python manage.py monitor_pipeline --dry-run
python manage.py monitor_pipeline --dry-run --format json
```

`--dry-run` hanya mencetak, tidak mengirim, dan tidak mencatat apa pun.

## Memasang jadwal 30 menit di Railway

1. Di proyek Railway: **New** -> **Empty Service** (atau duplikat layanan web),
   beri nama `pipeline-monitor`.
2. **Variables**: salin semua variabel layanan web (terutama `DATABASE_URL`
   dan pengaturan email Brevo), lalu tambahkan
   `MONITOR_RECIPIENTS=<alamat email admin>`. Kalau kosong, dipakai
   `HITL_REPORT_RECIPIENTS`.
3. **Settings** -> **Custom Start Command**: `python manage.py monitor_pipeline`
4. **Settings** -> **Cron Schedule**: `*/30 * * * *` (waktu UTC, selang
   minimal 5 menit).
5. Deploy. Setiap 30 menit layanan ini jalan, memeriksa, dan selesai.

Layanan ini terpisah dari worker, jadi tetap bisa memberi tahu saat worker mati.

## Ambang batas

Bisa diubah lewat opsi di Custom Start Command, misalnya
`python manage.py monitor_pipeline --queue-minutes 45 --stuck-minutes 60`:

- `--queue-minutes` (30): antrean dianggap tertahan jika lamaran tertua menunggu selama ini.
- `--stuck-minutes` (30): lamaran dianggap macet jika sedang diproses selama ini.
- `--repeat-hours` (6): jeda sebelum alert yang sama dikirim ulang.
- `--digest-hour` (9): jam ringkasan harian (waktu lokal).

Catatan: waktu tunggu dihitung dari simpan terakhir lamaran (saat diantrekan
atau diantrekan ulang), karena worker memperbarui status tanpa memperbarui
`updated_at`.
