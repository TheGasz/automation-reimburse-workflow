# Dokumen: SOP Keuangan 2026

## Bab 1: Ketentuan Umum Pengajuan Klaim & Batas Waktu

### Pasal 1.1: Batas Waktu Pengajuan & Validitas Struk (SOP-FIN-01.1)
category: general | effective_date: 2026-01-01 | policy_code: SOP-FIN-01.1
Seluruh pengajuan klaim reimbursement operasional karyawan wajib disertai bukti foto struk fisik atau nota digital resmi yang mencantumkan nama merchant/toko, tanggal transaksi, rincian item pembelian, dan total pembayaran dalam Rupiah.
Batas waktu maksimal pengajuan klaim adalah **14 hari kalender** sejak tanggal transaksi yang tertera pada struk. Klaim dengan tanggal struk lebih dari 14 hari dari tanggal pengajuan dinyatakan kedaluwarsa (expired) dan wajib ditolak otomatis (`auto_reject`) dengan kode pelanggaran `SOP-FIN-01.1`.

### Pasal 1.2: Larangan Klaim Ganda & Ambang Batas Auto-Approve (SOP-FIN-01.2)
category: general | effective_date: 2026-01-01 | policy_code: SOP-FIN-01.2
Setiap bukti struk hanya boleh diajukan satu kali. Sistem mendeteksi klaim duplikat (double claim) berdasarkan perceptual hash gambar dan sidik jari kombinasi `(merchant_name, receipt_date, total_amount)`. Klaim yang terdeteksi duplikat langsung ditolak otomatis (`auto_reject`).
Klaim dengan total nominal **<= Rp250.000** yang 100% patuh terhadap kebijakan SOP tanpa pelanggaran keras (`hard_violation`) maupun peringatan lunak (`soft_warning`) serta memiliki sisa kuota plafon bulanan mencukupi dapat disetujui secara otomatis (`auto_approve`). Klaim dengan nominal **> Rp250.000** wajib melalui persetujuan Manajer Finance (`needs_human_review`).

## Bab 2:Daftar Item Terlarang & Pengecualian Struk Gabungan

### Pasal 2.1: Barang dan Jasa yang Tidak Ditanggung Perusahaan (SOP-FIN-02.1)
category: general | effective_date: 2026-01-01 | policy_code: SOP-FIN-02.1
Perusahaan secara tegas melarang penggantian biaya (reimbursement) untuk item non-operasional atau kebutuhan pribadi berikut (`hard_violation`):
1. Minuman beralkohol (bir, wine, liquor, soju, cocktail beralkohol).
2. Produk tembakau, rokok konvensional, rokok elektrik (vape, pod, liquid), dan korek api.
3. Barang belanjaan pribadi rumah tangga, kosmetik, parfum, pakaian pribadi, mainan, atau voucher game/hiburan pribadi.
4. Denda tilang lalu lintas atau sanksi pelanggaran hukum pribadi.
Apabila seluruh item pada struk merupakan item terlarang, klaim wajib ditolak otomatis (`auto_reject`). Apabila dalam satu struk terdapat gabungan item operasional sah dan item terlarang/pribadi, klaim diberi penanda pelanggaran `SOP-FIN-02.1`, nominal `approved_amount` dipotong sebesar harga item terlarang, dan status diarahkan ke `needs_human_review`.

## Bab 3: Konsumsi Lembur, Jamuan Klien, & Makan Perjalanan Dinas

### Pasal 3.1: Plafon Makan Perjalanan Dinas & Konsumsi Lembur (SOP-FIN-03.1)
category: meals | effective_date: 2026-01-01 | policy_code: SOP-FIN-03.1
Penggantian biaya konsumsi makan dan minum diatur dengan rincian plafon sebagai berikut:
| Jenis Konsumsi | Batas Maksimal per Transaksi | Syarat Tambahan |
| :--- | :--- | :--- |
| Makan Harian Perjalanan Dinas | Rp75.000 / kali makan (maks Rp225.000 / hari) | Berlaku saat tugas luar kota |
| Makan Malam Lembur Karyawan | Rp50.000 / orang | Lembur minimal 3 jam di atas jam kerja normal |
| Konsumsi Lembur Akhir Pekan | Rp65.000 / orang | Wajib melampirkan referensi Surat Tugas Lembur (`soft_warning` jika tanpa referensi surat tugas) |
| Jamuan Makan Klien Bisnis | Rp150.000 / orang | Wajib menyebutkan nama klien/proyek pada catatan klaim (`needs_human_review` jika total > Rp250.000) |

### Pasal 3.2: Pembelian Kopi, Snack Rapat, & Air Mineral Cabang (SOP-FIN-03.2)
category: meals | effective_date: 2026-01-01 | policy_code: SOP-FIN-03.2
Pembelian konsumsi rapat internal cabang (air mineral dus, kopi, teh, snack rapat, roti) di minimarket (Indomaret, Alfamart, Superindo) atau toko kue dapat diklaim selama digunakan untuk kegiatan operasional kantor atau menjamu tamu cabang dengan batas wajar <= Rp250.000 per transaksi.

## Bab 4: Transportasi, Bahan Bakar, Tol, & Logistik Kurir

### Pasal 4.1: Transportasi Online, Taksi, BBM, Parkir, & E-Toll (SOP-FIN-04.1)
category: transport | effective_date: 2026-01-01 | policy_code: SOP-FIN-04.1
Biaya transportasi operasional yang dapat diajukan meliputi:
1. **Taksi / Ride-Hailing (Gojek, Grab, Bluebird):** Untuk perjalanan ke lokasi klien, gudang, bank, atau bandara.
2. **Bahan Bakar Minyak (BBM Pertamax/Pertalite/Solar):** Untuk kendaraan operasional cabang atau kunjungan dinas dengan mencantumkan tujuan perjalanan.
3. **Tarif Jalan Tol (E-Toll) & Parkir Resmi:** Struk fisik gardu tol, bukti top-up/riwayat pemotongan kartu e-toll (Flazz, E-Money, Brizzi, TapCash) khusus perjalanan dinas, serta karcis parkir resmi gedung/bandara.

### Pasal 4.2: Pengiriman Barang & Logistik Kurir Cabang (SOP-FIN-04.2)
category: transport | effective_date: 2026-01-01 | policy_code: SOP-FIN-04.2
Pengeluaran ekspedisi dan pengiriman barang/dokumen mendadak antar-cabang atau ke pelanggan (JNE, J&T, SiCepat, Lalamove, GoSend, GrabExpress, Pos Indonesia) dapat diklaim penuh berdasarkan resi pembayaran resmi. Pengiriman barang berat menggunakan armada sewa/kargo dengan nilai > Rp250.000 memerlukan verifikasi Manajer Finance (`needs_human_review`).

## Bab 5: Akomodasi Hotel & Perjalanan Dinas Luar Kota

### Pasal 5.1: Plafon Hotel & Penginapan Perjalanan Dinas (SOP-FIN-05.1)
category: accommodation | effective_date: 2026-01-01 | policy_code: SOP-FIN-05.1
Karyawan yang melakukan perjalanan dinas luar kota berhak atas penggantian biaya penginapan hotel bintang 2/3 atau guest house standar dengan plafon maksimal **Rp650.000 per malam**.
Biaya tambahan hotel yang bersifat pribadi seperti *minibar*, *laundry ekspres pribadi*, *spa/massage*, atau *pay-per-view movie* tidak ditanggung perusahaan (`SOP-FIN-05.1`) dan harus dikeluarkan dari perhitungan `approved_amount`. Karena biaya hotel umumnya melampaui Rp250.000, seluruh klaim akomodasi wajib melalui tinjauan Manajer Finance (`needs_human_review`).

## Bab 6: Kebutuhan Kantor Mendadak (ATK, Materai) & Medis Darurat

### Pasal 6.1: Pembelian ATK, Materai, & Kebutuhan Operasional Cabang (SOP-FIN-06.1)
category: office_supplies | effective_date: 2026-01-01 | policy_code: SOP-FIN-06.1
Pembelian kebutuhan mendadak operasional toko/cabang DB Klik seperti kertas HVS, kertas thermal printer kasir, lakban packing, bubble wrap, tinta printer, kabel LAN/ekstensi listrik, lampu toko, serta **materai tempel Rp10.000** untuk dokumen kontrak/berita acara dapat diklaim secara penuh. Pembelian peralatan kerja di atas Rp250.000 wajib disetujui oleh Manajer Finance (`needs_human_review`).

### Pasal 6.2: Klaim Kesehatan Rawat Jalan Darurat & P3K Operasional (SOP-FIN-06.2)
category: medical | effective_date: 2026-01-01 | policy_code: SOP-FIN-06.2
Pembelian perlengkapan P3K kotak obat cabang (betadine, plester, paracetamol, perban) atau biaya berobat jalan darurat akibat kecelakaan kerja ringan saat bertugas dapat diajukan dengan melampirkan kuitansi apotek/klinik resmi. Vitamin kecantikan, suplemen gym/fitness, atau perawatan estetika/skincare tidak ditanggung (`hard_violation` terhadap `SOP-FIN-06.2`).
