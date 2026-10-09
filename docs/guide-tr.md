# Türkçe Kullanım Rehberi

## Projenin amacı

FlightOps Quality, uçuş operasyon kayıtlarını analiz öncesinde denetleyen küçük bir
Python paketidir. Yerel saatleri UTC gözlemlerine dönüştürür; eksik veya çelişkili
veriyi bulgularla açıklar ve ham kayıtları izlenebilir bir denetim raporunda korur.
Bir veri ambarına yükleme öncesinde kullanılabilecek bir toplu işleme katmanıdır.

## Kurulum ve ilk analiz

Python 3.9 ve üzeriyle uyumludur; yeni ortamlarda bakımı süren bir Python sürümü
kullanın. Paket henüz PyPI'da yayımlanmamıştır. Kaynak depodan kurulum:

```bash
git clone https://github.com/ubeydgencer/flightops-quality.git
cd flightops-quality
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .

flightops-quality examples/synthetic_flights.csv --output example-output
```

`example-output/audit.html` raporu tarayıcıda açılabilir. Aynı klasörde `audit.json`
ve kayıtların kabul, karantina ve tekrar durumlarını içeren JSONL dosyaları bulunur.
Her çalıştırmada yeni bir çıktı klasörü seçin; var olan sonuçlar korunur.
CLI, atomik klasör yayımlamak için macOS/Linux'a özgü API'leri kullanır. Windows
için var olan hedefi değiştirmeyen yeniden adlandırma davranışı uygulanır; bu
platformda henüz doğrulanmamıştır. Desteklenmeyen diğer platformlarda kısmi rapor
yayımlamadan durur.

## Desteklenen veri formatları

| Format | Girdi ve bağlam |
|---|---|
| Canonical CSV | `source`, `record_id`, `service_date`, `carrier`, `flight_number`, `origin`, `destination` kimlik alanları; isteğe bağlı zamanlar ve durum bayrakları. |
| BTS Reporting Carrier CSV | Kaynak alan adları korunur; havaalanı kodlarını IANA saat dilimlerine eşleyen, çağıranın sağladığı bir JSON dosyası gerekir. |

Canonical zamanlar ISO biçimindedir. UTC ofseti olmayan zamanlar için kalkışta
`origin_timezone`, varışta `destination_timezone` gerekir. Yaz saati geçişindeki
iki anlamlı saat, açık bir ofset veya ilgili `<field>_fold` değeriyle çözülür.
Paket belirsiz veya var olmayan yerel saatleri sessizce düzeltmez.

BTS örneği:

```bash
flightops-quality examples/synthetic_bts.csv --format bts \
  --timezones examples/airport_timezones.json \
  --midnight-policy end --output example-output-bts
```

Örnek saat dilimi haritası yalnızca üç havaalanını kapsar. Gerçek kullanım için
kaynak döneme uygun kendi eşlemenizi sağlayın. Planlanan `CRSDepTime=2400` için
`start` veya `end` politikası zorunludur; sentetik örnek, hizmet tarihinin sonunu
bilerek kullanır. Bu tarih bağını gerçek kaynak sürümüyle doğrulayın.

Tarihler işaretli kalkış gecikmesi ve geçen sürelerden türetilir, ardından yerel
saat alanlarıyla karşılaştırılır. Tek başına bir varış saati tarih üretmez.
İptal sonrasında kapıya dönüş kaydı korunabilir; başka havaalanına yönlendirilen
uçuşun gerçek varışı planlanan varış havaalanının saat dilimine atanmaz.
IANA veritabanı olmayan sistemlerde `python -m pip install '.[timezone]'` kullanın.

## Veri kalitesi kontrolleri

Hatalar kaydı karantinaya alır. Uyarılar eksik gözlemi korur; gerekli veri yoksa
ilgili ölçüm `null` kalır. Kapı zamanları ve pist zamanları ayrı tutulur.
Kontroller saat sırasını, yerel saat/süre tutarlılığını, durum bayraklarını,
zorunlu kimlik alanlarını ve kayıt tekrarlarını kapsar.

Aynı `(source, record_id)` altında eşit ham JSON içerikleri tekrar olarak ayrı
raporlanır. Farklı içerikler varsa grubun bütün üyeleri karantinaya alınır; paket
bir kaydı sessizce seçmez. Ham satırlar, hash değerleri, kaynak satır numaraları ve
türetilen zamanların kaynak alanları sonuçların geriye izlenmesini sağlar.
Kuralların kodları ve çözüm açıklamaları [kural kataloğundadır](rules.md).

Toplu veri kalite eşikleri isteğe bağlıdır. Şu örnek bilerek **1 çıkış koduyla**
biter ve inceleme için raporu korur:

```bash
flightops-quality examples/synthetic_flights.csv --output quality-review \
  --min-arrival-coverage-percent 80 \
  --min-otp-eligible-flights 10 \
  --max-quarantine-rate-percent 5
```

Eşikleri veriyi tüketen uygulama seçer. Minimum kapsama ve uygun uçuş sayısı
kontrolleri `>=`, maksimum karantina oranı kontrolü `<=` kullanır. Yüzdeler sonlu
ve 0–100 arasında; minimum adet 0–`2**63 - 1` arasında tam sayı olmalıdır.
`quality_gate` sonucu yapılandırılmış bütün kontroller geçerse `passed`, en az
biri başarısızsa `failed`, eşik yoksa `not_configured` olur. Eşikler veri girdisini
denetler; uçuş emniyeti standardı veya havayolu OTP hedefi değildir.

CLI çıkış kodları: rapor yazıldıktan sonra **0**; başarısız kalite eşiğinde veya
`--fail-on-error` ile karantina bulunduğunda **1**; geçersiz girdi/yapılandırmada
**2**. Geçersiz yapılandırma kısmi rapor oluşturmaz. Ayrıntılı formüller ve API
örnekleri [kalite eşikleri belgesindedir](quality-gates.md).

## OTP ve veri kapsamı

`arrival_otp_15_completed`, kabul edilen benzersiz, iptal edilmemiş ve başka
havaalanına yönlendirilmemiş uçuşlardan geçerli varış gecikmesi olanları kullanır.
Gecikme **15 dakikadan küçükse** zamanında sayılır; tam 15 dakika geç sayılır.
Boş OTP paydası `null` üretir. Bu grubun paydası BTS'nin yayımladığı toplam
operasyon metriğiyle aynı değildir.

Sentetik canonical örneğin ölçümleri:

| Ölçüm | Sonuç |
|---|---:|
| Girdi kayıtları | 11 |
| Kabul / karantina / tam tekrar | 6 / 4 / 1 |
| Kabul edilen normal uçuşlar | 3 |
| Varış OTP'sine uygun uçuşlar | 2 |
| Varış gecikmesi eksik normal uçuşlar | 1 |
| Varış verisi kapsamı | 2 / 3 ≈ %66,67 |
| Varış OTP'si | 1 / 2 = %50 |
| Karantina oranı | 4 / (6 + 4) = %40 |

Kapsama, normal kabul edilen uçuşların ne kadarında kullanılabilir varış verisi
olduğunu; OTP, uygun uçuşların ne kadarının zamanında vardığını gösterir. İki
iptal ve bir yönlendirilmiş uçuş kapsama grubunun dışındadır. Tam tekrarlar
karantina oranının paydasına girmez; çelişkili kimlik grubundaki bütün karantina
kayıtları girer.

Normal uçuş yoksa kapsama `null` olur ve yapılandırılmış minimum kapsama kontrolü
eşik sıfır olsa bile başarısızdır. Rapor, ölçümlerin paylarını, paydalarını ve
popülasyon açıklamalarını birlikte içerir.

## ETL entegrasyonu

SQLite örneği bütün ham kayıtları saklar, yalnızca kabul edilen uçuşları analiz
tablosuna yükler. Ayrı SQL sorgusu uygun uçuş paydasını ve OTP'yi hesaplar:

```bash
python examples/etl_sqlite.py example-output/audit.json example-output/warehouse.db
```

Kalite kapısı `failed` olan bir audit varsayılan olarak yüklenmez. Bulguların
incelendiği bir keşif çalışmasında açık bir istisna kullanılabilir:

```bash
python examples/etl_sqlite.py quality-review/audit.json quality-review/reviewed.db \
  --allow-failed-quality-gate
```

Bu seçenek kayıtları yeniden kabul etmez ve rapordaki kalite sonucunu değiştirmez.
Python `load` fonksiyonunda aynı seçim `allow_failed_quality_gate=True` ile
yapılır; varsayılanı `False` değeridir. Kalite kapısı bulunmayan eski auditler ve
`not_configured` sonuçlar yüklenebilir. Yeni veritabanı yolu seçin; atomik dosya
yayımlama, hard link destekleyen bir dosya sistemi gerektirir.

Python veri akışında `QualityPolicy` ve `evaluate_quality` doğrudan
`flightops_quality` paketinden alınabilir. Aynı politikayı
`audit_document(report, quality_policy=policy)` çağrısına vererek karar ve audit
arasında tutarlılık sağlayın.

## Doğrulama ve kapsam

Bu sürüm, sentetik uç durum testlerine ek olarak BTS'nin Ocak, Mart ve Kasım 2025
dosyalarındaki JFK, LAX ve ORD arasındaki kayıtlarla sınanmış bir toplu işleme
alpha sürümüdür. Ocak kohortunda 2.929 kaynak kaydından 2.928'i kabul edilmiş,
saat ve süre alanları çelişen bir kayıt karantinaya alınmıştır. Varış gecikmesi ve
havada kalma süresi karşılaştırmasına
giren 2.909 kayıtta kaynakla eşleşme görülmüştür; 11 iptal, 8 diversion ve bir
saat çelişkisi açık dışlama nedenleriyle raporlanmıştır.

[Ocak kaynağı, tekrar çalıştırma komutu ve sonuçları](bts-2025-01-route-cohort.md)
ayrı belgede yer alır.

[Mart kohortunda](bts-2025-03-route-cohort.md) 3.079 kaydın tamamı kabul edilmiş;
iki hedef alan, karşılaştırmaya giren 3.061 normal uçuşta eşleşmiştir. 9 iptal ve
9 diversion karşılaştırma dışında açıkça sayılmıştır. Kabul edilen normal
uçuşlarda varış kapsamı %100, OTP %84,4169'dur; bunlar farklı ölçümlerdir.

Mart raporu, 9 Mart ilkbahar saat geçişini kapsayan türetilmiş zaman pencerelerini
de gösterir. Tüm durumları içeren 3.079 kabul kaydının SOBT → SIBT pencereleri
arasında 15, 3.061 normal kabul kaydının AOBT → AIBT pencereleri arasında 18
pencerede ofset farkı bulunmuştur. Her havaalanı diliminin kendi ofseti aynı UTC
penceresinin iki ucunda karşılaştırılır; çıkış ve varış dilimleri birbirleriyle
karşılaştırılmaz. Bu sonuç mutlak UTC doğruluğuna ilişkin bağımsız bir kanıt
değildir.

[Kasım kohortunda](bts-2025-11-route-cohort.md) 3.246 kayıttan 3.245'i kabul
edilmiş; iki hedef alan, karşılaştırmaya giren 3.152 normal uçuşta eşleşmiştir.
87 iptal, 6 diversion ve bir belirsiz planlanan saat karşılaştırma dışında açıkça
sayılmıştır. 2 Kasım'da LAX'taki planlanan 01:20 saati iki kez oluştuğu ve
`departure_fold` seçilmediği için bu kayıt karantinaya alınmıştır. Bulgu, geçerli
yerel saatin hangi oluşumunu kastettiğinin çözülmediğini gösterir; kaynağın
hatalı saat bildirdiğini kanıtlamaz. Kabul edilen normal uçuşlarda varış kapsamı
%100, OTP %75,9201'dir.

Kasım'da tüm durumları içeren 3.245 kabul kaydının planlanan pencereleri arasında
16, 3.152 normal kabul kaydının gerçekleşen pencereleri arasında 14 pencerede
ofset farkı bulunmuştur. Çözülmüş bir zaman penceresinde ofsetin geri gitmesi ile
henüz bir UTC anına bağlanamamış tekrarlı yerel saat farklı bulgulardır.
Altı zaman alanının ek incelemesinde tekrarlı saatin ilk oluşumuna düşen bir
kabul edilmiş kalkış anı (ATOT, fold 0) bulunmuştur; ikinci oluşuma düşen kabul
edilmiş zaman yoktur. İki fold seçimini sınayan sentetik testler bu gerçek veri
kapsamından ayrı değerlendirilir.

Bu çalışmalar ayın bütün havaalanlarını, mutlak UTC
tarihlerinin bağımsız doğruluğunu veya bir havayolunun üretim verisini
doğrulamaz. Paketle gelen CSV örnekleri sentetiktir; gerçek kaynak dosyası ayrıca
indirilir. Testlerin ve dağıtım kontrollerinin sürüm bazında sonuçları
[doğrulama belgesinde](validation.md), teknik sınırlar [tasarım belgesinde](design.md)
yer alır.

Paket bütün veri grubunu bellekte tutar. CLI boyut ve kayıt sınırları uygular;
doğrudan API kullanan uygulamalar kendi toplam girdi sınırlarını da koymalıdır.
Tekrar üretilebilir sonuçlar için Python sürümünü, saat dilimi veritabanını ve
havaalanı eşlemesini sabitleyin. Güven sınırı ve güvenlik bildirimi yöntemi
[güvenlik politikasında](../SECURITY.md) açıklanır.

### Kaydedilmiş sonuçların HTML raporu

Depodaki JSON kanıtını çevrimdışı bir HTML raporuna dönüştürün:

```bash
python examples/bts_validation_html.py \
  --input docs/evidence/bts-2025-11-route-cohort.json \
  --output bts-report-2025-11.html
```

`bts-report-2025-11.html` dosyasını tarayıcıda açın. Rapor statiktir; JavaScript veya
uzak sunucudan yazı tipi kullanmaz. Kaynak arşivinin ve saat dilimi eşlemesinin hash
değerlerini, kaynak dönemini, çalışma ortamını, kayıt durumlarını ve saat
bulgularıyla kayıtlı ofset pencerelerini gösterir. Karşılaştırmaya giren kayıtlarla
dışlama nedenlerinin
paydaları ve kaynak grubunun OTP'siyle kabul grubunun OTP'si ayrı tutulur.
HTML oluşturmak yeni bir veri doğrulaması çalıştırmaz; kaydedilmiş kanıtı sunar.

Yeni bir çıktı dosyası seçin; var olan dosyalar üzerine yazılmaz. Resmî arşivi
yeniden inceleyen `examples/validate_bts_month.py` komutu da `validation.json` ve
`cohort.csv` yanında `validation.html` üretir. Gerçek aylık kaynak ve tam kohort
pakete eklenmez; Ocak ve Kasım JSON kanıtlarında sınırlı kaynak bulgusu örnekleri
bulunur. Mart ve Kasım kanıtları sınırlı sayıda türetilmiş ofset penceresi örneği
içerir.
