# Panduan Menggunakan Bot Signal dengan Docker

Menjalankan bot TradingView Signal ini dengan Docker memiliki banyak keuntungan:
1. **Lebih Stabil**: Bot berjalan dalam lingkungan terisolasi yang konsisten.
2. **Auto-Restart**: Jika bot crash atau error koneksi parah, Docker akan otomatis merestartnya (`restart: unless-stopped`).
3. **Konfigurasi Mudah**: Semua variabel setting (`TELEGRAM_BOT_TOKEN`, dll) bisa diatur terpusat di file konfigurasi.

## Prasyarat
Pastikan Anda sudah menginstall Docker dan Docker Compose (Docker Desktop jika di Windows).

---

## 🚀 Cara Menjalankan Bot

### Langkah 1: Atur Setting di `docker-compose.yml`
Buka file `docker-compose.yml` dengan text editor (seperti Notepad, VSCode). Anda bisa mengubah pengaturan di bagian `environment:`, seperti:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MAX_SYMBOLS`
- dll.

Nilai standar (default) saat ini sudah disesuaikan sama persis dengan yang ada di `run_bot.bat` Anda.

### Langkah 2: Build & Jalankan Bot

Buka Terminal (Bisa pakai **Command Prompt** / **PowerShell** / **Terminal di VS Code**) di dalam folder project ini. Jalankan perintah:

```bash
docker-compose up -d --build
```

**Penjelasan Lengkapnya:**
- `up` : Menjalankan container.
- `-d` : (Detached mode) Berjalan di background. Anda bisa menutup terminal dan bot akan tetap jalan!
- `--build` : Memberitahu docker untuk mem-build ulang image (harus dipakai saat pertama kali dijalankan, atau kalau script `.py` diedit).

### Langkah 3: Melihat Log (Mengecek Apakah Bot Jalan)

Karena bot berjalan secara *background* (tidak tampil di layar command prompt langsung), Anda dapat melihat log proses/pesannya dengan memanggil:

```bash
docker-compose logs -f
```

*(Tekan `Ctrl+C` jika ingin keluar dari layar tampilan log ini, tenang saja bot tetap akan berjalan meski log ditutup)*

---

## 🛠️ Perintah Berguna Lainnya

- **Menghentikan bot:**
  ```bash
  docker-compose down
  ```

- **Melihat status bot apakah sedang berjalan:**
  ```bash
  docker-compose ps
  ```

- **Update Code:**
  Jika Anda mengedit skrip `tradingview_signal_bot.py`, Anda perlu mematikan dan mem-build ulang dockernya:
  ```bash
  docker-compose down
  docker-compose up -d --build
  ```

## Catatan Tentang Gambar / Chart
Gambar chart hasil _generate_ otomatis dari matplotlib masih akan tersimpan di PC Anda, tepatnya di dalam folder `charts` proyek ini. Ini karena adanya konfigurasi `volumes: - ./charts:/app/charts` yang menghubungkan folder dalam Docker ke folder di Windows Anda.
