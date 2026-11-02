# Helper bot benchmark (Instagram + YouTube)

Measured 2026-11-02 with `scripts/bench_helpers.py`. Applied to the DB (`helper_bots.priority`,
`settings.relay_order:youtube:<quality>`); this file is the saved reference list.

```
HELPER BOTLAR TEZLIK SINFLARI (sekund, link yuborilgandan media kelgunicha)
Sinflar: 1 superfast <=5s · 2 fast <=12s · 3 norma <=25s · 4 slow <=60s · 5 juda sekin/javobsiz/sifat mos emas
(vaqt: link yuborilgandan video kelguncha, sinov kutishi 5s ayirilgan)

INSTAGRAM (reel)
  1 superfast: @PTB_InstagramDownloader_Bot 4s [1080p], @SaveAsBot 4s [720p], @MaxSaveBot 4s [720p], @MegaSaverBot 4s [720p], @Shazam_music_downloader_bot 4s [720p], @TinglaBot 4s [720p], @allsaverbot 4s [720p], @savedinstabot 4s [720p], @Saqlabot 4s [720p], @SaveZBot 4s [720p], @videoyukla 4s [720p], @embedybot 4s [720p], @vide 4s [720p]
  2 fast: @TTPapaBot 10s [720p], @instagram_load_bot 11s [720p]
  5 juda sekin/javobsiz: @instadowbot 2s [junk/subscription prompt: 😊 Botdan foydalanish uchun, quyida], @SaveYoutubeBot 3s [junk/subscription prompt: ‍К сожалению, я не умею скачивать ], @skachat_robot 3s [junk/subscription prompt: 😊 Botdan foydalanish uchun, quyida], @SaveXT_bot 63s [stalled: helper stopped responding], @ssVideoBot 63s [stalled: helper stopped responding], @Threads_DownloadRobot 64s [stalled: helper stopped responding], @Youtube_dwnldr_bot 65s [stalled: helper stopped responding]

YOUTUBE · avtomatik sifat (tugmasiz)
  1 superfast: @ssVideoBot 4s [480p]
  2 fast: @Saqlabot 6s [320p], @TTPapaBot 6s [720p], @TinglaBot 7s [320p], @savedinstabot 7s [320p], @SaveYoutubeBot 9s [720p]
  3 norma: @videoyukla 17s [720p], @Shazam_music_downloader_bot 23s [720p]
  4 slow: @vide 26s [720p]
  5 juda sekin/javobsiz: @SaveAsBot 2s [helper error: Скачивание с YouTube пока не поддерживается!], @instadowbot 2s [junk/subscription prompt: 😊 Botdan foydalanish uchun, quyida], @SaveZBot 3s [helper error: You sent link from unsupported resource. Bot w], @skachat_robot 3s [junk/subscription prompt: 😊 Botdan foydalanish uchun, quyida], @embedybot 63s [stalled: helper stopped responding], @PTB_InstagramDownloader_Bot 63s [stalled: helper stopped responding], @SaveXT_bot 63s [stalled: helper stopped responding], @MegaSaverBot 63s [stalled: helper stopped responding], @allsaverbot 63s [stalled: helper stopped responding], @instagram_load_bot 64s [stalled: helper stopped responding], @Threads_DownloadRobot 65s [stalled: helper stopped responding], @Youtube_dwnldr_bot 65s [stalled: helper stopped responding], @MaxSaveBot 66s [stalled: helper stopped responding]

YOUTUBE · 360p
  2 fast: @Saqlabot 6s [320p], @TinglaBot 7s [320p], @savedinstabot 7s [320p], @videoyukla 11s [360p]
  3 norma: @vide 22s [360p]
  4 slow: @TTPapaBot 26s [360p], @SaveYoutubeBot 37s [360p]
  5 juda sekin/javobsiz: @Shazam_music_downloader_bot 4s [gave 720p], @ssVideoBot 4s [gave 480p]

YOUTUBE · 480p
  3 norma: @videoyukla 17s [480p]
  4 slow: @TTPapaBot 26s [480p], @SaveYoutubeBot 31s [480p], @vide 39s [480p]
  5 juda sekin/javobsiz: @ssVideoBot 4s [gave 1080p], @Shazam_music_downloader_bot 4s [gave 720p], @savedinstabot 7s [gave 320p], @Saqlabot 7s [gave 320p], @TinglaBot 7s [gave 320p]

YOUTUBE · 720p
  1 superfast: @Shazam_music_downloader_bot 4s [720p]
  2 fast: @videoyukla 6s [720p], @vide 7s [720p], @SaveYoutubeBot 9s [720p]
  3 norma: @TTPapaBot 18s [720p]
  5 juda sekin/javobsiz: @ssVideoBot 4s [gave 1080p], @Saqlabot 7s [gave 320p], @TinglaBot 7s [gave 320p], @savedinstabot 7s [gave 320p]

YOUTUBE · 1080p
  1 superfast: @ssVideoBot 4s [1080p]
  4 slow: @TTPapaBot 26s [1080p]
  5 juda sekin/javobsiz: @Shazam_music_downloader_bot 4s [gave 720p], @Saqlabot 7s [gave 320p], @vide 7s [gave 720p], @TinglaBot 7s [gave 320p], @savedinstabot 7s [gave 320p], @SaveYoutubeBot 15s [gave 720p], @videoyukla 69s [stalled: helper stopped responding]

YOUTUBE · MP3
  3 norma: @videoyukla 18s, @vide 22s
  4 slow: @TTPapaBot 26s, @SaveYoutubeBot 33s
  5 juda sekin/javobsiz: @Shazam_music_downloader_bot 12s [helper error: Не удалось распознать песню.
Пришли другой фра], @ssVideoBot 63s [stalled: helper stopped responding], @savedinstabot 66s [stalled: helper stopped responding], @Saqlabot 66s [stalled: helper stopped responding], @TinglaBot 67s [stalled: helper stopped responding]

QO'LLANILGAN SOZLAMALAR
- Prioritet (kichik raqam = oldin so'raladi): 10-23 superfast guruh, 34-36 fast guruh, keyingilar zaxira. Guruhdagi bot javob bermasa, keyingi guruhga o'tiladi (har safar 2 tadan poyga).
- YouTube har bir tugma uchun alohida tartib saqlandi:
  360p: saqlabot, tinglabot, savedinstabot, videoyukla, vide, ttpapabot, saveyoutubebot
  480p: videoyukla, ttpapabot, saveyoutubebot, vide
  720p: shazam_music_downloader_bot, videoyukla, vide, saveyoutubebot, ttpapabot
  1080p: ssvideobot, ttpapabot
  MP3: videoyukla, vide, ttpapabot, saveyoutubebot
  avtomatik: ssvideobot, saqlabot, ttpapabot, tinglabot, savedinstabot, saveyoutubebot, videoyukla, shazam_music_downloader_bot, vide
- O'chirilgan (ishlamadi): instadowbot va skachat_robot (reklama tarmog'i subgram.org orqali homiy kanal/bot talab qiladi, a'zo bo'lmadim), SaveXT_bot, Youtube_dwnldr_bot (javob bermadi).
- Eslatma: bot javobi keshlangan bo'lishi mumkin; sinov bitta Instagram reel va bitta YouTube video (5 daqiqa) bilan, 8 bot parallel. Qolgan platformalar (TikTok, Pinterest va h.k.) bu safar sinalmadi.
```
