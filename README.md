# Tata Surya Berita Kabupaten Bandung (versi gratis)

Semua komponen gratis: GitHub (repositori publik + Actions + Pages), model sentimen IndoRoBERTa dari Hugging Face, YouTube Data API (opsional).

## Pasang
1. Unggah semua isi folder ini ke repositori GitHub (termasuk folder .github).
2. Settings > Pages > Source: branch `main`, folder `/ (root)`.
3. (Opsional) Settings > Secrets and variables > Actions > Secrets: `YOUTUBE_API_KEY` (gratis dari Google Cloud Console, aktifkan YouTube Data API v3).
4. Tab Actions > "Perbarui data berita" > Run workflow. Eksekusi pertama 5-10 menit karena mengunduh model; berikutnya lebih cepat.

## Beralih ke penilai Claude (berbayar, lebih akurat)
Tambahkan secret `ANTHROPIC_API_KEY`, lalu di Settings > Secrets and variables > Actions > Variables buat variabel `USE_CLAUDE` bernilai `1`.

## Catatan
- Model dilatih dari ulasan dan komentar, bukan berita, jadi judul berita sering dinilai netral. Skrip menambah aturan kata penanda sederhana (misalnya "korupsi", "banjir", "apresiasi") untuk kasus netral.
- Penyaringan "benar-benar tentang Kabupaten Bandung" memakai kata kunci wilayah dan nama kecamatan, bukan pemahaman bahasa, jadi kadang meleset.
- Instagram, TikTok, dan Facebook tidak disertakan karena tidak ada pencarian publik yang bisa dipakai bebas.
