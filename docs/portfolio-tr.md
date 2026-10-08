# Veri mühendisliği portföyünde nasıl anlatılır?

Bu proje, havayolu operasyon verisini analiz etmeden önce doğruluk ve izlenebilirlik
kurallarını uygulayan bir Python paketidir. Uçuş verilerinin saat dilimi, gece aşımı,
iptal ve diversion semantiğini küçük bir API içinde gösterir.

## Görüşmede gösterilecek akış

1. Sentetik ham CSV'deki belirsiz DST saati, çelişkili kimlik ve tekrar kaydı göster.
2. CLI ile audit üret; her satırın nereye gittiğini ve hangi kurala takıldığını aç.
3. Negatif gecikmenin korunmasını ve 15 dakika OTP sınırını açıklayarak SQL sonucunu göster.
4. Ham satır hash'i, dosya hash'i ve timestamp provenance üzerinden sonucu geriye izle.
5. Eksik veri için neden sıfır veya rastgele tarih üretmediğini anlat.

CV için doğru bir ifade:

> Python ile açık kaynak uçuş operasyon veri-kalitesi paketi geliştirdim; BTS CSV
> adaptörü, UTC/DST doğrulaması, çelişkili kayıt karantinası ve izlenebilir JSON/HTML
> raporları oluşturdum. Sentetik uç durum testleri ve SQLite/SQL analiz örneğiyle
> veri akışının satır mutabakatını ve KPI paydalarını doğruladım.

Gerçek bir havayolu verisiyle çalışıldığı, şirket tarafından kullanıldığı veya
sertifikalı bir operasyon sistemi olduğu söylenmemeli. v0.1 sentetik verilerle
sınanmış bir alpha sürümdür; gerçek veri üzerinde ikinci doğrulama gerekir.

## İşe alım açısından çıkarım

[Turkish Technology ürünleri](https://turkishtechnology.com/tr/products) arasında
Turnaround AI ve uçak kuyruk ataması bulunuyor. Bu, operasyon verisi üzerine bir
portföyün alanla ilişkisini destekler; işe alım talebi ya da projeye özel ilgi
kanıtı değildir. Güçlü sinyal, paketin sayısından çok problem seçimi, veri
kontratları, anlamlı testler, kullanılabilir örnek ve sınırlamaların açık olmasıdır.

Sonraki faydalı çalışma, tek bir tarihli BTS ayını indirip resmi alanlarla
karşılaştırmak; tarihsel havaalanı eşlemesini ve hata oranlarını belgelemektir.
Kullanıcı geri bildiriminden önce ikinci benzer paket çıkarmak öncelikli değildir.
