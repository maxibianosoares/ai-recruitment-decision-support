# Laporan mingguan Human-in-the-Loop dengan Hermes

## Pembagian tugas
| Bagian | Dikerjakan oleh |
|---|---|
| Menghitung angka (disetujui / berlawanan dengan AI / menunggu) | `python manage.py weekly_hitl_report` — kode biasa, tanpa AI, tanpa nama |
| Membuat laporan naratif mingguan dari angka tersebut | Hermes, memakai `SKILL.md` |
| Keputusan akhir rekrutmen | Admin (tidak berubah) |

Perintah itu juga menghasilkan laporan lengkap sendiri (`--format markdown`),
jadi sistem tetap berguna tanpa Hermes.

## Menjalankan perintah
    python manage.py weekly_hitl_report                          # laporan teks, 4 minggu terakhir
    python manage.py weekly_hitl_report --format json --weeks 8  # untuk Hermes
    python manage.py weekly_hitl_report --lang id                # label bahasa Indonesia
    python manage.py weekly_hitl_report --week-ending 2026-10-25

## Cara aman memberi data ke Hermes
Hermes menjalankan perintah terminal, jadi **jangan beri kredensial database
produksi kepada Hermes**. Pola yang disarankan:

1. Anda sendiri (login Railway Anda) membuat file JSON:
       railway run python manage.py weekly_hitl_report --format json > hitl_inbox\week.json
   Bila koneksi database gagal dari laptop, periksa apakah `DATABASE_URL`
   memakai alamat internal Railway; gunakan alamat publik database bila ada.
2. Beri Hermes akses hanya ke folder `hitl_inbox` (baca) dan `reports` (tulis).
3. Hermes membaca `week.json` memakai skill ini dan menulis `reports/hitl-<tanggal>.md`.

Untuk demo ke Prof Jo tanpa data nyata: jalankan perintah terhadap database
lokal berisi data demo (`seed_demo_data`) — angkanya sintetis, bukan data pelamar.

## Pemasangan skill di Hermes
Salin folder ini ke `~/.hermes/skills/weekly-hitl-report/ (isi folder hermes/skills/weekly-hitl-report/)` (format agentskills.io),
lalu jadwalkan tugas mingguan di Hermes, misalnya:

    Setiap Senin pukul 09:00: baca hitl_inbox/week.json dengan skill
    weekly-hitl-report, tulis laporan ke reports/, dan beri tahu saya jika
    ada angka "agreement_flag_inconsistencies" di atas 0.

Langkah Hermes ini BELUM diuji oleh pembuat patch (tidak ada Hermes di
lingkungan pengembangan); yang diuji hanya perintah dan perhitungannya.

## Cara membaca angka
- **Sesuai AI**: arah keputusan panitia sama dengan rekomendasi AI.
- **Berlawanan (override)**: arah berlawanan. Keputusan manusia terkunci setelah
  dicatat, sehingga "diubah" dihitung sebagai override.
- Minggu dengan kurang dari 5 keputusan ditandai *low volume*.
- Laporan tidak menunjukkan siapa yang benar, AI atau panitia.
