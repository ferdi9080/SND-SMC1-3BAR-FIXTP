v17_3_nocancel_fix
==================
Perbaikan:
- CORNIX_LEVERAGE sekarang didefinisikan (tidak ada NameError lagi)
- Tambah retry + reconnect untuk TradingView datafeed (mengurangi error: "Connection to remote host was lost")

Jika masih sering disconnect:
- naikkan TV_RETRY menjadi 8-10
- naikkan TV_RETRY_WAIT menjadi 3-5
