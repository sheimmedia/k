import os
import time
import logging
import random
import pickle
import json
import re
import functools
import requests
import psutil
import pandas as pd

from typing import List, Dict, Optional, Union, Tuple, Any, Callable
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

import google.generativeai as genai

# Selenium ile ilgili import'lar
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.remote.webelement import WebElement
from webdriver_manager.chrome import ChromeDriverManager

from apscheduler.schedulers.background import BackgroundScheduler

# Selenium istisnaları
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
    ElementNotInteractableException,
    NoSuchElementException,
    ElementClickInterceptedException
)



def setup_logging(log_file: str = 'casino_twitter_bot.log') -> logging.Logger:
    logger = logging.getLogger('CasinoTwitterBot')
    logger.setLevel(logging.INFO)
    logger.handlers = []
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Dosyaya log kaydetme - Rotasyon ile
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Konsola log kaydetme
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.stream.reconfigure(errors='replace')
    logger.addHandler(console_handler)

    return logger


# Logger nesnesini oluştur
logger = setup_logging()


@dataclass
class TwitterAccount:
    """
    Twitter hesap bilgilerini depolamak için veri sınıfı.
    Kullanıcı adı, şifre, proxy ve oturum yolu bilgilerini içerir.
    """
    username: str
    password: str
    proxy: Optional[str] = None
    session_path: Optional[str] = None
    
    
class TwitterBot:
    def __init__(self, account: TwitterAccount, gemini_api_key: str = None):
        """
        TwitterBot sınıfının başlatıcı metodu.

        :param account: Kullanılacak Twitter hesabı bilgileri
        :param gemini_api_key: Gemini API anahtarı (opsiyonel)
        """
        self.account = account
        self.username = account.username  # Doğru atama
        self.password = account.password  # Doğru atama
        self.proxy = account.proxy if account.proxy else None  # Tek atama
        self.driver = None
        self.wait = None
        self.posted_tweets = set()
        self.session_dir = Path("sessions")
        self.session_path = self.session_dir / f"{account.username}_session.pkl"
        self.session_dir.mkdir(exist_ok=True)
        
        try:
            self.initialize_driver()
            logger.info(f"[{self.account.username}] WebDriver başarıyla başlatıldı")
        except Exception as e:
            logger.error(f"[{self.account.username}] WebDriver başlatma hatası: {e}")
            raise

        if gemini_api_key:
            try:
                self.initialize_gemini(gemini_api_key)
                logger.info(f"[{self.account.username}] Gemini AI başarıyla yapılandırıldı")
            except Exception as e:
                logger.error(f"[{self.account.username}] Gemini AI yapılandırma hatası: {e}")
                raise

        self.tweets_data = []
        self.analysis_results = {}
        self.betting_data = {'matches': [], 'odds': {}, 'promotions': [], 'sports_calendar': {}, 'trending_bets': []}
        self.performance_metrics = {'rtp_rates': {}, 'popular_games': [], 'jackpot_amounts': {}, 'user_feedback': [], 'winning_patterns': {}}

        

    def initialize_driver(self) -> None:
        """
        Chrome WebDriver'ını gelişmiş ayarlarla başlatır.
        Tarayıcı performansını maksimize eder, bellek kullanımını optimize eder,
        algılanma riskini minimize eder ve timeout sorunlarını çözer.
        """
        try:
            chrome_options = Options()
            
            # ----- TEMEL AYARLAR -----
            # Pencere yapılandırması
            chrome_options.add_argument("--start-maximized")  # Ekranı maksimize eder
            # chrome_options.add_argument("--window-size=1920,1080")  # Alternatif olarak belirli bir çözünürlük
            # chrome_options.add_argument("--headless=new")  # Gerekirse yeni headless modu (gizli mod)
            
            # ----- GÜVENLİK & KARARLILIK AYARLARI -----
            chrome_options.add_argument("--no-sandbox")  # Güvenli olmayan ancak performans için gerekli
            chrome_options.add_argument("--disable-dev-shm-usage")  # Paylaşılan bellek sorunlarını çözer
            chrome_options.add_argument("--disable-crash-reporter")  # Çökme raporlayıcısını devre dışı bırakır
            chrome_options.add_argument("--disable-in-process-stack-traces")  # Stack izlerini devre dışı bırakır
            chrome_options.add_argument("--disable-logging")  # Browser logging devre dışı
            chrome_options.add_argument("--disable-extensions")  # Eklentileri devre dışı bırakır
            chrome_options.add_argument("--disable-infobars")  # Bilgi çubuklarını kaldırır
            chrome_options.add_argument("--ignore-certificate-errors")  # Sertifika hatalarını yok sayar
            chrome_options.add_argument("--ignore-ssl-errors")  # SSL hatalarını yok sayar
            chrome_options.add_argument("--allow-running-insecure-content")  # Güvensiz içerik çalıştırmaya izin verir
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")  # Otomasyonu gizler
            
            # ----- PERFORMANS OPTİMİZASYONLARI -----
            # GPU ve görsel rendering optimizasyonları
            chrome_options.add_argument("--disable-gpu")  # GPU kullanımını kapatır
            chrome_options.add_argument("--disable-software-rasterizer")
            chrome_options.add_argument("--disable-webgl")
            chrome_options.add_argument("--disable-3d-apis")
            chrome_options.add_argument("--disable-webrtc")  # WebRTC devre dışı bırak
            chrome_options.add_argument("--disable-accelerated-2d-canvas")
            chrome_options.add_argument("--disable-accelerated-video-decode")
            chrome_options.add_argument("--disable-accelerated-video-encode")
            chrome_options.add_argument("--disable-gpu-compositing")
            chrome_options.add_argument("--disable-gpu-vsync")
            chrome_options.add_argument("--disable-remote-fonts")  # Uzak fontları devre dışı bırakma
            chrome_options.add_argument("--force-device-scale-factor=1")  # Ölçek faktörünü 1'e sabitler
            
            # Bellek ve önbellek optimizasyonları
            chrome_options.add_argument("--disk-cache-size=1")
            chrome_options.add_argument("--media-cache-size=1")
            chrome_options.add_argument("--disable-application-cache")  # Uygulama önbelleğini devre dışı bırakır
            chrome_options.add_argument("--disable-cache")  # Önbelleği tamamen devre dışı bırakır
            chrome_options.add_argument("--disable-backing-store-limit")  # Backing store limitini kaldırır
            chrome_options.add_argument("--disable-browser-side-navigation")  # Tarayıcı taraflı navigasyonu kaldırır
            chrome_options.add_argument("--aggressive-cache-discard")  # Agresif önbellek temizleme
            chrome_options.add_argument("--disable-back-forward-cache")  # Geri-ileri önbelleğini devre dışı bırakır
            
            # Arkaplan aktivitelerini minimize etme
            chrome_options.add_argument("--disable-background-networking")
            chrome_options.add_argument("--disable-background-timer-throttling")
            chrome_options.add_argument("--disable-backgrounding-occluded-windows")
            chrome_options.add_argument("--disable-breakpad")
            chrome_options.add_argument("--disable-component-extensions-with-background-pages")
            chrome_options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees,IsolateOrigins,site-per-process")
            chrome_options.add_argument("--disable-ipc-flooding-protection")
            chrome_options.add_argument("--disable-client-side-phishing-detection")
            chrome_options.add_argument("--disable-default-apps")
            chrome_options.add_argument("--disable-hang-monitor")
            chrome_options.add_argument("--disable-notifications")
            chrome_options.add_argument("--disable-popup-blocking")
            chrome_options.add_argument("--disable-prompt-on-repost")
            chrome_options.add_argument("--disable-sync")
            chrome_options.add_argument("--disable-domain-reliability")  # Alan adı güvenilirlik hizmetini devre dışı bırakır
            
            # JavaScript performans ayarları
            chrome_options.add_argument("--js-flags=--max-old-space-size=128,--expose-gc,--single-process")
            chrome_options.add_argument("--disable-javascript-harmony-shipping")  # JS harmony özelliklerini devre dışı bırakır
            
            # Güvenlik ve erişim ayarları
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--allow-file-access-from-files")
            chrome_options.add_argument("--disable-site-isolation-trials")  # Site izolasyon denemelerini devre dışı bırakır
            
            # ----- BOT TESPİT KORUMALARI -----
            # Otomasyon imzalarını gizleme
            chrome_options.add_experimental_option("excludeSwitches", [
                "enable-automation", 
                "enable-logging",
                "ignore-certificate-errors",
                "safebrowsing-disable-download-protection",
                "safebrowsing-disable-auto-update"
            ])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            # Fingerprinting koruması 
            chrome_options.add_argument("--disable-features=EnableEphemeralFlashPermission")
            chrome_options.add_argument("--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure")
            
            # Mobil kullanıcı ajanı ayarı (isteğe bağlı - maskelemeye yardımcı olabilir)
            # user_agents = [
            #     "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/85.0.4183.109 Mobile/15E148 Safari/604.1",
            #     "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.105 Mobile Safari/537.36",
            #     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36",
            # ]
            # chrome_options.add_argument(f"--user-agent={random.choice(user_agents)}")
            
            # Kullanıcı profili (tutarlı bir deneyim için) - ihtiyaca göre aktifleştirin
            # import os
            # user_data_dir = os.path.join(os.path.expanduser("~"), "chrome_profiles", self.account.username)
            # os.makedirs(user_data_dir, exist_ok=True)
            # chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
            
            # ----- TERCIHLER VE TARAYICI AYARLARI -----
            # Gelişmiş tarayıcı tercihleri
            prefs = {
                # Bildirim ayarları
                "profile.default_content_setting_values.notifications": 2,  # 2 = Engelle
                "profile.managed_default_content_settings.plugins": 2,
                "profile.managed_default_content_settings.popups": 2,
                "profile.managed_default_content_settings.geolocation": 2,
                "profile.managed_default_content_settings.media_stream": 2,
                "profile.managed_default_content_settings.images": 1,  # 1 = İzin ver (performans için 2 yapabilirsiniz)
                
                # PDF, indirme ve dil ayarları
                "plugins.always_open_pdf_externally": True,  # PDF'leri harici olarak aç
                "download.default_directory": "/dev/null",  # İndirmeleri devre dışı bırak
                "translate.enabled": False,  # Çeviriyi devre dışı bırak
                
                # Dil ve bölgesel ayarlar
                "intl.accept_languages": "tr,en-US",  # Tercih edilen diller
                "translate_whitelists": {},  # Otomatik çeviri için beyaz liste
                
                # Önbellek ayarları
                "profile.default_content_settings.cookies": 1,  # 1 = İzin ver
                "profile.cookie_controls_mode": 0,  # 0 = Tüm çerezlere izin ver
                "profile.block_third_party_cookies": False,  # Üçüncü taraf çerezlerini engelleme
                
                # Yazı tipi ve medya ayarları
                "webkit.webprefs.minimum_font_size": 10,  # Minimum yazı tipi boyutu
                "webkit.webprefs.default_font_size": 16,  # Varsayılan yazı tipi boyutu
                
                # Performans ayarları
                "profile.password_manager_enabled": False,  # Şifre yöneticisini devre dışı bırak
                "credentials_enable_service": False,  # Otomatik giriş özelliğini devre dışı bırak
                "profile.default_content_setting_values.automatic_downloads": 1,  # Otomatik indirmelere izin ver
            }
            
            chrome_options.add_experimental_option("prefs", prefs)
            
            # ----- TIMEOUT AYARLARI -----
            # Doğrudan tarayıcı timeout ayarları için (programatik olarak uygulanır)
            # Bunlar driver oluşturulduktan sonra uygulanacak
            
            # ChromeDriver'ı başlatma
            try:
                service = Service(ChromeDriverManager().install())
                
                # Eğer service parametresinde service_args destekleniyorsa
                service_args = ['--verbose', '--log-path=chromedriver.log']
                service = Service(ChromeDriverManager().install(), service_args=service_args)
                
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                
                # Timeout ayarları
                self.driver.set_page_load_timeout(180)  # Sayfa yükleme zaman aşımını 180 saniyeye ayarla
                self.driver.set_script_timeout(180)  # Script zaman aşımını 180 saniyeye ayarla
                
                # WebDriverWait için uzun timeout ayarı (daha sabırlı bekleme)
                self.wait = WebDriverWait(self.driver, 180, poll_frequency=0.5)
                logger.info(f"[{self.account.username}] WebDriver başarıyla başlatıldı (gelişmiş ayarlarla)")
                
                # CDP üzerinden ek ayarlar (gelişmiş tarayıcı kontrolü)
                # Özel ağ ve performans ayarlarını etkinleştirmek için
                self.driver.execute_cdp_cmd("Network.enable", {})
                
                # Ağ trafiğini optimize et
                self.driver.execute_cdp_cmd("Network.setBypassServiceWorker", {"bypass": True})
                
                # Önbellek devre dışı bırak (opsiyonel)
                self.driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": True})
                
                # JavaScript hata sayfalarını gizle
                self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                    "source": """
                    // Hata sayfalarını ve çeşitli tarayıcı özelliklerini gizle
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    
                    // Otomasyon durumunu gizle
                    Object.defineProperty(navigator, 'plugins', {
                        get: function() { return [1, 2, 3, 4, 5]; }
                    });
                    
                    // Dil tespitini yanıltma
                    Object.defineProperty(navigator, 'languages', {
                        get: function() { return ['tr-TR', 'tr', 'en-US', 'en']; }
                    });
                    
                    // Açık bilgileri gizle
                    window.chrome = { runtime: {} };
                    """
                })
                
            except Exception as e:
                # Alternatif başlatma yöntemi
                logger.warning(f"[{self.account.username}] Service kullanımı başarısız: {e}, alternatif yöntem deneniyor")
                self.driver = webdriver.Chrome(ChromeDriverManager().install(), options=chrome_options)
                
                # Aynı timeout ayarlarını alternatif yöntemde de uygula
                self.driver.set_page_load_timeout(180)
                self.driver.set_script_timeout(180)
                self.wait = WebDriverWait(self.driver, 180, poll_frequency=0.5)
                
                logger.info(f"[{self.account.username}] WebDriver alternatif yöntemle başlatıldı (gelişmiş ayarlarla)")

        except Exception as e:
            logger.error(f"[{self.account.username}] WebDriver başlatma hatası: {e}")
            # Hatayı yukarı taşıma, ancak driver'ı None olarak bırakmamaya çalışma
            raise


 
    # Belirli aralıklarla tarayıcıyı yenile
    def refresh_browser_state(self):
        """Tarayıcı oturumunu periyodik olarak tazeleyerek bellek sızıntılarını önler"""
        if random.random() < 0.2:  # %20 ihtimalle
            self.driver.execute_script("window.gc();")  # Çöp toplayıcıyı強制的に実行
            self.clear_browser_cache()
            
    def smart_retry(func, max_retries=3, retry_delay=5):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(self, *args, **kwargs)
                except Exception as e:
                    retries += 1
                    logger.warning(f"[{self.account.username}] İşlem başarısız, {retries}/{max_retries} kez yeniden deneniyor: {e}")
                    time.sleep(retry_delay * (2 ** (retries - 1)) * (0.5 + random.random()))
                    if retries >= max_retries / 2:
                        self.driver.refresh()
                        time.sleep(5)
                raise Exception(f"[{self.account.username}] İşlem {max_retries} deneme sonrasında da başarısız oldu")
        return wrapper
    
    def wait_for_page_load_complete(self, timeout=30):
        """Sayfanın tamamen yüklenmesini bekler"""
        end_time = time.time() + timeout
        while time.time() < end_time:
            page_state = self.driver.execute_script('return document.readyState;')
            if page_state == 'complete':
                return True
            time.sleep(0.5)
        return False
    
    def synchronize_operation(self, operation_function, *args, **kwargs):
        """İşlemleri Twitter'ın dinamik yapısına göre senkronize eder"""
        # Sayfanın stabil olmasını bekle
        self.wait_for_network_idle()
        
        # İşlemi gerçekleştir
        result = operation_function(*args, **kwargs)
        
        # İşlemin tamamlanmasını bekle ve reaktif olarak kontrol et
        self.wait_for_operation_complete()
        
        return result
    
    def monitor_performance(self):
        """CPU ve bellek kullanımını izler, gerekirse düzeltici önlemler alır"""
       
        
        process = psutil.Process(self.driver.service.process.pid)
        cpu_percent = process.cpu_percent(interval=1)
        memory_percent = process.memory_percent()
        
        logger.debug(f"CPU kullanımı: %{cpu_percent:.1f}, Bellek kullanımı: %{memory_percent:.1f}")
        
        # Eğer kaynaklar aşırı kullanılıyorsa
        if cpu_percent > 80 or memory_percent > 75:
            logger.warning("Yüksek kaynak kullanımı tespit edildi, tarayıcı yenileniyor...")
            self.driver.refresh()
            time.sleep(5)
            
    def setup_operation_scheduler(self):
        """İşlemleri akıllı bir şekilde planlar"""
        scheduler = BackgroundScheduler()
        
        # Bellek temizleme görevi - her 30 dakikada bir
        scheduler.add_job(self.clear_browser_cache, 'interval', minutes=30)
        
        # Hız sınırı denetleyicisi - her 5 dakikada bir
        scheduler.add_job(self.check_rate_limits, 'interval', minutes=5)
        
        scheduler.start()
        
    def check_twitter_status(self):
        """Twitter'ın erişilebilirliğini ve API durumunu kontrol eder"""
        try:
            response = requests.get("https://api.twitterstat.us/", timeout=5)
            status_data = response.json()
            
            if not status_data.get("all_services_operational", True):
                logger.warning("Twitter servisleri tamamen operasyonel değil, işlemler geçici olarak duraklatılıyor...")
                time.sleep(300)  # 5 dakika bekle
                return False
                
            return True
        except Exception:
            # Twitter status API'sine erişilemiyorsa, varsayılan olarak devam et
            return True
        
    def safe_page_navigation(self, url):
        """Sayfa geçişlerini güvenli ve optimize edilmiş şekilde gerçekleştirir"""
        max_attempts = 3
        attempt = 0
        
        while attempt < max_attempts:
            try:
                # Sayfaya git
                self.driver.get(url)
                
                # Sayfa yükleme durumunu izle
                load_timeout = time.time() + 45
                while time.time() < load_timeout:
                    ready_state = self.driver.execute_script('return document.readyState')
                    if ready_state == 'complete':
                        # Ek AJAX isteklerinin tamamlanmasını bekle
                        time.sleep(1)
                        return True
                    time.sleep(0.5)
                    
                # Zaman aşımı oldu, sayfayı yenile
                self.driver.refresh()
                attempt += 1
                
            except Exception as e:
                attempt += 1
                logger.warning(f"Sayfa yükleme hatası ({attempt}/{max_attempts}): {e}")
                time.sleep(3)
        
        return False
    
    
    def check_login_status(self) -> bool:
        try:
            self.driver.get("https://x.com/home")
            time.sleep(3)
            # Giriş yapılmışsa tweet oluşturma butonu görünür
            self.wait.until(EC.presence_of_element_located((By.XPATH, "//a[@href='/compose/post']")))
            logger.info(f"[{self.account.username}] Oturum aktif")
            return True
        except Exception as e:
            logger.warning(f"[{self.account.username}] Oturum kontrol hatası: {e}")
            return False
    
    
    def recover_from_session_error(self):
        """Oturum hatalarını tespit eder ve otomatik kurtarma sağlar"""
        try:
            # Oturum durumunu kontrol et
            is_logged_in = self.check_login_status()
            
            if not is_logged_in:
                logger.warning("Oturum düşmüş, yeniden giriş yapılıyor...")
                self.login()
                return True
                
            return True
            
        except Exception as e:
            logger.error(f"Oturum kurtarma sırasında hata: {e}")
            
            # Çok ciddi bir hata varsa tarayıcıyı yeniden başlat
            try:
                self.driver.quit()
                time.sleep(3)
                self.initialize_driver()
                self.login()
                return True
            except Exception:
                return False
        
    def initialize_gemini(self, api_key):
        """
        Gemini AI modelini başlatır.

        :param api_key: Gemini API anahtarı
        """
        try:
            genai.configure(api_key=api_key)
            self.gemini_model = genai.GenerativeModel("gemini-1.5-pro")
            logger.info(f"[{self.account.username}] Gemini AI başarıyla yapılandırıldı")
            return True
        except Exception as e:
            logger.error(f"[{self.account.username}] Gemini AI yapılandırma hatası: {e}")
            return False

            # Model adını güncelleyin - gemini-1.5-pro veya güncel model adını kullanın
            # API sürümüne uygun model isimlerini kontrol edelim
            try:
                # Önce kullanılabilir modelleri listeleyin
                models = genai.list_models()
                model_names = [model.name for model in models]
                logger.info(
                    f"[{self.account.username}] Kullanılabilir modeller: {model_names}")

                # Uygun modeli seçelim - tercih sırası
                preferred_models = ["gemini-1.5-pro",
                                    "gemini-1.0-pro", "gemini-pro"]

                selected_model = None
                for model_name in preferred_models:
                    if any(model_name in m for m in model_names):
                        selected_model = model_name
                        break

                if not selected_model:
                    # Yedek plan: Herhangi bir gemini modelini kullan
                    for model in model_names:
                        if "gemini" in model.lower() and "pro" in model.lower():
                            selected_model = model
                            break

                if not selected_model:
                    # Hiçbir uygun model bulunamazsa ilk modeli kullan
                    selected_model = model_names[0] if model_names else "gemini-pro"

                logger.info(
                    f"[{self.account.username}] Seçilen Gemini modeli: {selected_model}")
                
                # Gelişmiş model yetenekleri için opsiyonları ayarla
                generation_config = {
                    "temperature": 0.8,  # Daha yaratıcı yanıtlar için
                    "top_p": 0.95,       # Çeşitliliği artırmak için
                    "top_k": 40,         # Daha odaklı sonuçlar için
                    "max_output_tokens": 2048  # Daha kapsamlı yanıtlar
                }
                
                # Modeli yapılandırılmış ayarlarla oluştur
                self.gemini_model = genai.GenerativeModel(
                    model_name=selected_model,
                    generation_config=generation_config
                )

            except Exception as e:
                # Model listesini alamazsak varsayılan olarak güncel modeli deneyelim
                logger.warning(
                    f"[{self.account.username}] Model listesi alınamadı: {e}")
                logger.info(
                    f"[{self.account.username}] Varsayılan modeli deneniyor: gemini-1.5-pro")
                self.gemini_model = genai.GenerativeModel("gemini-1.5-pro")

            # Test mesajı ile modeli kontrol edelim
            test_response = self.gemini_model.generate_content(
                "Merhaba, bu bir test mesajıdır. Casino ve bahis pazarlaması için 5 yaratıcı fikir verir misin?")
            logger.info(
                f"[{self.account.username}] Gemini API test yanıtı alındı: {test_response.text[:150]}...")

            logger.info(
                f"[{self.account.username}] Gemini AI başarıyla yapılandırıldı")
            return True
        except Exception as e:
            logger.error(
                f"[{self.account.username}] Gemini AI yapılandırma hatası: {e}")
            return False

    def ai_driven_casino_strategy(self):
        """
        Gemini AI tarafından yönetilen bahis/casino sosyal medya stratejisi
        """
        try:
            # Betting data (ayrı bir toplama fonksiyonu olmadan)
            betting_data = {
                'matches': [
                    {"home": "Fenerbahçe", "away": "Galatasaray", "odds": {"1": 2.50, "X": 3.30, "2": 2.70}},
                    {"home": "Beşiktaş", "away": "Trabzonspor", "odds": {"1": 2.10, "X": 3.20, "2": 3.40}},
                    {"home": "Adana Demirspor", "away": "Antalyaspor", "odds": {"1": 1.95, "X": 3.25, "2": 3.80}}
                ],
                'promotions': [
                    {"title": "Hoşgeldin Bonusu", "description": "%100 ilk yatırım bonusu", "expiry": "Süresiz"},
                    {"title": "Bahis Boost", "description": "Kombine kuponlarda %25 ekstra kazanç", "expiry": "Bu hafta sonu"},
                    {"title": "Casino Freespin", "description": "100 bedava dönüş hakkı", "expiry": "Önümüzdeki 7 gün"}
                ]
            }
            
            # Güncel performans ve hedef analizi için prompt
            strategy_prompt = f"""
            Casino/Bahis Twitter Hesabı Stratejik Pazarlama Analizi:

            Mevcut Performans Verileri:
            - Hesap takipçi sayısı ve etkileşim oranları
            - En başarılı bahis pazarlama içerikleri
            - Rakiplerin trend stratejileri

            Aktif Bahis Etkinlikleri:
            {json.dumps(betting_data['matches'][:3], indent=2, ensure_ascii=False)}
            
            Güncel Promosyonlar:
            {json.dumps(betting_data['promotions'][:3], indent=2, ensure_ascii=False)}

            Stratejik Hedefler:
            1. Yeni bahisçi kullanıcı kazanımı
            2. Kayıtlı kullanıcıların dönüşüm oranını artırma
            3. Özel casino bonusları ve promosyonlar için farkındalık
            4. Sorumlu kumar farkındalığı ve yasal uyarılar
            5. Kazanç hikayelerine dayalı pazarlama
            10. Kayıt Olduktan sonraki bonuslardan bahset
            11. İnsanları Kayıt Olmaya teşvik et
            
            İhtiyaç Duyulan İçerik Stratejileri:
            1. Büyük spor etkinlikleri öncesi bahis teşvik mesajları
            2. Maç tahmini ve analiz içerikleri
            3. Casino oyunları tanıtımları
            4. Promosyon ve bonus duyuruları
            5. "Bugünün bahis fırsatları" formatında içerikler
            
            ÇIKTI FORMATI:
            1. Günlük içerik planlaması (tweet zamanları ve içerik türleri)
            2. Haftalık bahis/casino promosyon takvimi
            3. En etkili 5 tweet taslağı
            4. Hashtagler ve etiketleme stratejisi
            5. Hedef kitle analizi ve demografik öneriler
            6. İçerik performans metrikleri
            
            """

            # Gemini AI'dan stratejik yanıt alma
            logger.info(f"[{self.account.username}] Casino/Bahis stratejisi için Gemini'den yanıt bekleniyor...")
            strategy_response = self.gemini_model.generate_content(strategy_prompt)
            
            # Yanıtı yapılandırılmış formata dönüştürmek için analiz et
            structured_strategy = self.parse_ai_strategy_response(strategy_response.text)
            
            # Stratejinin uygulanması - tweet şablonlarını veritabanına kaydet
            if 'tweet_templates' in structured_strategy and structured_strategy['tweet_templates']:
                self.save_tweet_templates(structured_strategy['tweet_templates'])
                logger.info(f"[{self.account.username}] {len(structured_strategy['tweet_templates'])} tweet şablonu kaydedildi")
                
            logger.info(f"[{self.account.username}] Gemini AI destekli bahis stratejisi uygulandı")
            return True

        except Exception as e:
            logger.error(f"[{self.account.username}] Casino/Bahis stratejisi hatası: {e}")
            return False
            
    def parse_ai_strategy_response(self, strategy_text):
        """
        Gemini AI'dan gelen strateji yanıtını analiz ederek yapılandırılmış veri formatına dönüştürür
        """
        try:
            # Gemini'den gelen metni bu yapıya çevirmeye çalış
            strategy_sections = {
                'daily_content': [],
                'weekly_promotions': [],
                'tweet_templates': [],
                'hashtag_strategy': [],
                'target_audience': {},
                'performance_metrics': {}
            }
            
            # Basit regex ile tweet şablonlarını çıkarmaya çalış
            tweet_templates = []
            lines = strategy_text.split('\n')
            for line in lines:
                if len(line.strip()) > 10 and (
                    "tweet" in line.lower() or 
                    "#" in line or 
                    "bahis" in line.lower() or 
                    "casino" in line.lower() or
                    "bonus" in line.lower() or
                    "kazanç" in line.lower()
                ):
                    # Başındaki numaralandırmaları ve madde işaretlerini temizle
                    cleaned_line = re.sub(r'^\d+[\.\)]\s*|\-\s*|•\s*', '', line.strip())
                    if len(cleaned_line) > 20 and len(cleaned_line) < 280:
                        tweet_templates.append(cleaned_line)
            
            # En az 3 tweet şablonu oluştur
            if len(tweet_templates) < 3:
                # Varsayılan tweet şablonları
                tweet_templates = [
                    "🎲 Bugün şansınızı test etmeye ne dersiniz? En popüler slot oyunlarımıza göz atın, 50 Free Spin hediyemiz var! 18+ #Casino #Slot @alobetgiris",
                    "⚽ Haftanın en çok oynanan maçlarında yüksek oranlar sizi bekliyor! İlk Kayıt Olanlara Deneme Bonusu! 18+ #Bahis #YüksekOran @alobetgiris",
                ]
            
            # En fazla 5 şablonu kaydet
            strategy_sections['tweet_templates'] = tweet_templates[:5]
            
            # Hashtag stratejisi
            hashtags = re.findall(r'#\w+', strategy_text)
            if hashtags:
                strategy_sections['hashtag_strategy'] = list(set(hashtags))
            else:
                strategy_sections['hashtag_strategy'] = ["#Bahis", "#Casino", "#Bonus", "@alobetgiris", "#Jackpot"]
                
            return strategy_sections
                
        except Exception as e:
            logger.error(f"[{self.account.username}] Strateji yanıtı ayrıştırma hatası: {e}")
            # Basit bir varsayılan strateji döndür
            return {
                'daily_content': ['Sabah: Günün maçları', 'Öğle: Yüksek oranlar', 'Akşam: Canlı bahis'],
                'tweet_templates': [
                    "Bugünün en yüksek oranlı maçları burada! Hemen üye ol, ilk yatırımına %100 bonus kazan! 🎲 #Bahis #Kazanç @alobetgiris 18+",
                    "Hafta sonu dev maçlara dev oranlar! Sen de hemen bahisini yap, kazananlar arasına katıl! #BahisFırsatı @alobetgiris 18+",
                    "5TL'lik bahse 500TL kazanç şansı! Bu fırsat kaçmaz! Hemen üye ol, fırsatları kaçırma! #Casino #Şans @alobetgiris 18+"
                ],
                'hashtag_strategy': ['#Bahis', '#Casino', '#Kazanç', '#Jackpot', '#BüyükOran', '@alobetgiris']
            }
            
    def implement_casino_strategy(self, strategy):
        """
        Gemini AI'nın önerdiği casino/bahis stratejisini uygular
        
        :param strategy: Yapılandırılmış strateji verisi
        """
        try:
            logger.info(f"[{self.account.username}] Casino stratejisi uygulanıyor: {len(strategy['tweet_templates'])} tweet şablonu")
            
            # Tweet şablonlarını veritabanına kaydet
            self.save_tweet_templates(strategy['tweet_templates'])
            
            # Günün tweet'i için şablon seç ve gönder
            if strategy['tweet_templates'] and random.random() < 0.7:  # %70 şansla bir tweet gönder
                tweet_template = random.choice(strategy['tweet_templates'])
                
                # Tweet şablonunu özelleştir (güncel oranlar, promosyonlar vb.)
                customized_tweet = self.customize_betting_tweet(tweet_template)
                
                # Hashtag'leri ekle
                if strategy['hashtag_strategy'] and len(strategy['hashtag_strategy']) > 0:
                    hashtags = ' '.join(random.sample(strategy['hashtag_strategy'], 
                                                     min(3, len(strategy['hashtag_strategy']))))
                    if not any(tag in customized_tweet for tag in strategy['hashtag_strategy']):
                        customized_tweet = f"{customized_tweet} {hashtags}"
                
                # Karakter limiti kontrolü
                if len(customized_tweet) > 280:
                    customized_tweet = customized_tweet[:277] + "..."
                
                # Tweet'i gönder
                self.post_tweet(customized_tweet)
                logger.info(f"[{self.account.username}] Strateji bazlı bahis tweet'i gönderildi: {customized_tweet[:50]}...")
            
            # İçerik takvimini kaydet
            if 'daily_content' in strategy and strategy['daily_content']:
                self.save_content_calendar(strategy['daily_content'])
                logger.info(f"[{self.account.username}] İçerik takvimi güncellendi: {len(strategy['daily_content'])} madde")
            
            # Hedef kitle bilgilerini kaydet
            if 'target_audience' in strategy and strategy['target_audience']:
                self.update_audience_targeting(strategy['target_audience'])
                logger.info(f"[{self.account.username}] Hedef kitle stratejisi güncellendi")
            
            return True
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Casino stratejisi uygulama hatası: {e}")
            return False
    
    def save_tweet_templates(self, templates):
        """
        Tweet şablonlarını bir JSON dosyasına kaydeder
        
        :param templates: Tweet şablonları listesi
        """
        try:
            templates_dir = Path("tweet_templates")
            templates_dir.mkdir(exist_ok=True)
            
            template_file = templates_dir / f"{self.account.username}_casino_templates.json"
            
            # Şablonları dosyaya kaydet
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(templates, f, ensure_ascii=False, indent=2)
                
            logger.info(f"[{self.account.username}] {len(templates)} tweet şablonu kaydedildi")
            return True
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Tweet şablonu kaydetme hatası: {e}")
            return False
    
    def customize_betting_tweet(self, template):
        """
        Bahis tweet şablonunu güncel verilerle özelleştirir
        
        :param template: Tweet şablonu
        :return: Özelleştirilmiş tweet
        """
        try:
            # Rastgele takım/lig adları
            teams = ["Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor", 
                     "Manchester United", "Liverpool", "Barcelona", "Real Madrid",
                     "Bayern Münih", "PSG", "Juventus", "Inter"]
                     
            leagues = ["Süper Lig", "Premier Lig", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Şampiyonlar Ligi"]
            
            # Rastgele oran ve bonus değerleri
            odds = [1.50, 1.65, 1.85, 2.10, 2.35, 2.50, 2.75, 3.00, 3.25, 3.50]
            bonuses = [50, 100, 150, 200, 250, 300, 500]
            
            # Metinde yer tutucuları değiştir
            result = template
            
            # {takim} yer tutucularını değiştir
            team_placeholders = re.findall(r'\{takim\d*\}', template)
            for placeholder in team_placeholders:
                result = result.replace(placeholder, random.choice(teams))
            
            # {lig} yer tutucularını değiştir
            if '{lig}' in template:
                result = result.replace('{lig}', random.choice(leagues))
            
            # {oran} yer tutucularını değiştir
            if '{oran}' in template:
                result = result.replace('{oran}', str(random.choice(odds)))
            
            # {bonus} yer tutucularını değiştir
            if '{bonus}' in template:
                result = result.replace('{bonus}', str(random.choice(bonuses)))
                
            # {tarih} yer tutucusunu değiştir
            if '{tarih}' in template:
                today = datetime.now().strftime("%d.%m.%Y")
                result = result.replace('{tarih}', today)
                
            # Özelleştirilmiş tweet'i döndür
            return result
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Tweet özelleştirme hatası: {e}")
            return template  # Hata durumunda orijinal şablonu döndür
            
    def save_content_calendar(self, content_items):
        """
        İçerik takvimini kaydet
        
        :param content_items: İçerik takvimi maddeleri
        """
        try:
            calendar_dir = Path("content_calendar")
            calendar_dir.mkdir(exist_ok=True)
            
            calendar_file = calendar_dir / f"{self.account.username}_calendar.json"
            
            # Mevcut takvimi yükle
            calendar_data = {"last_updated": datetime.now().isoformat(), "items": []}
            if calendar_file.exists():
                with open(calendar_file, 'r', encoding='utf-8') as f:
                    try:
                        calendar_data = json.load(f)
                    except json.JSONDecodeError:
                        pass
            
            # Yeni maddeleri ekle
            calendar_data["last_updated"] = datetime.now().isoformat()
            calendar_data["items"] = content_items
            
            # Takvimi kaydet
            with open(calendar_file, 'w', encoding='utf-8') as f:
                json.dump(calendar_data, f, ensure_ascii=False, indent=2)
                
            logger.info(f"[{self.account.username}] İçerik takvimi güncellendi: {len(content_items)} madde")
            return True
            
        except Exception as e:
            logger.error(f"[{self.account.username}] İçerik takvimi kaydetme hatası: {e}")
            return False
            
    def update_audience_targeting(self, audience_data):
        """
        Hedef kitle verilerini günceller
        
        :param audience_data: Hedef kitle verileri
        """
        try:
            targeting_dir = Path("audience_targeting")
            targeting_dir.mkdir(exist_ok=True)
            
            targeting_file = targeting_dir / f"{self.account.username}_targeting.json"
            
            # Veriyi kaydet
            with open(targeting_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "last_updated": datetime.now().isoformat(),
                    "audience_data": audience_data
                }, f, ensure_ascii=False, indent=2)
                
            logger.info(f"[{self.account.username}] Hedef kitle verileri güncellendi")
            return True
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Hedef kitle verisi kaydetme hatası: {e}")
            return False
        
        
    def load_tweet_suggestions_from_json(self):
        """Twitter analiz dosyalarından tweet önerilerini yükler ve linkleri ekler"""
        try:
            # Analiz dosyalarının bulunduğu dizin
            analysis_dir = Path("tweet_analyses")
            if not analysis_dir.exists():
                logger.warning(f"[{self.account.username}] Analiz dizini bulunamadı")
                return []
                
            # Kullanıcıya özel analiz dosyalarını bul
            user_files = list(analysis_dir.glob(f"*{self.account.username}*.json"))
            
            if not user_files:
                logger.warning(f"[{self.account.username}] Analiz dosyası bulunamadı")
                return []
                
            # En son analiz dosyasını al
            latest_file = max(user_files, key=lambda x: x.stat().st_mtime)
            
            # JSON dosyasını oku
            with open(latest_file, 'r', encoding='utf-8') as f:
                analysis_data = json.load(f)
                
            # Tweet önerilerini al
            if 'suggestions' in analysis_data and analysis_data['suggestions']:
                # Kullanılacak bahis linkleri listesi
                bet_links = [
                    "cutt.ly/mrlOjHcY"

                ]
                
                # Orijinal önerileri al
                original_suggestions = analysis_data['suggestions']
                processed_suggestions = []
                
                # Her bir öneriyi işle ve link ifadelerini gerçek bir link ile değiştir
                for suggestion in original_suggestions:
                    # Başındaki numaralandırmayı kaldır (örn: "1. ", "2. " gibi)
                    cleaned_suggestion = re.sub(r'^\d+\.\s*', '', suggestion)
                    
                    # Farklı link formatlarını değiştir (büyük/küçük harf duyarlılığı olmadan)
                    random_link = f"https://{random.choice(bet_links)}"
                    
                    # Çeşitli link formatlarını değiştir
                    for link_pattern in ["[Link]", "[link]", "\\[Link\\]", "\\[link\\]", "[Link]", "Link", "link"]:
                        cleaned_suggestion = re.sub(re.escape(link_pattern), random_link, cleaned_suggestion, flags=re.IGNORECASE)
                    
                    # Log çıktısıyla değişimin yapıldığından emin ol
                    if random_link in cleaned_suggestion:
                        logger.info(f"[{self.account.username}] Link başarıyla eklendi: {random_link}")
                    else:
                        logger.warning(f"[{self.account.username}] Link eklenemedi! Tweet: {cleaned_suggestion}")
                    
                    processed_suggestions.append(cleaned_suggestion)
                
                logger.info(f"[{self.account.username}] {len(processed_suggestions)} tweet önerisi yüklendi")
                return processed_suggestions
            else:
                logger.warning(f"[{self.account.username}] Analiz dosyasında öneri bulunamadı")
                return []
                
        except Exception as e:
            logger.error(f"[{self.account.username}] JSON dosyasından tweet önerisi yükleme hatası: {e}")
            return []
        
        
    def load_betting_site_info(self):
        """Bahis sitesi bilgilerini txt dosyasından okur"""
        try:
            # Bahis bilgileri dosyasının yolu
            betting_info_file = "1king.txt"
            
            # Dosyanın var olup olmadığını kontrol et
            if not os.path.exists(betting_info_file):
                logger.warning(f"[{self.account.username}] Bahis bilgileri dosyası bulunamadı: {betting_info_file}")
                return {}
            
            # Dosyayı oku
            with open(betting_info_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Bilgileri işle
            betting_info = {}
            current_section = "general"
            
            lines = content.split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Bölüm başlığı mı kontrol et
                if line.endswith(':'):
                    current_section = line[:-1].lower().replace(' ', '_')
                    betting_info[current_section] = []
                    continue
                
                # Madde işareti varsa temizle
                if line.startswith('- '):
                    line = line[2:]
                    
                # Mevcut bölüme ekle
                if current_section in betting_info:
                    betting_info[current_section].append(line)
                else:
                    betting_info[current_section] = [line]
            
            # Ana değerleri ayıkla
            for key in list(betting_info.keys()):
                if key.startswith('site_adı'):
                    betting_info['site_name'] = betting_info[key][0]
                elif key.startswith('url'):
                    betting_info['url'] = betting_info[key][0]
            
            logger.info(f"[{self.account.username}] Bahis bilgileri yüklendi: {len(betting_info)} bölüm")
            return betting_info
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Bahis bilgileri yükleme hatası: {e}")
            return {}
    
    
    def generate_ai_betting_tweets(self, num_tweets=3, betting_theme="mixed"):
        """
        Gemini AI kullanarak özelleştirilmiş ve etkili bahis/casino tweet'leri oluşturur.
        Bahis site bilgilerini txt dosyasından okuyarak kullanır.
        
        :param num_tweets: İstenen tweet sayısı
        :param betting_theme: Bahis teması ("sports", "casino", "promotions", "mixed")
        :return: Tweet metinleri listesi
        """
        try:
            # Bahis site bilgilerini oku
            betting_info = self.load_betting_site_info()
            
            # Yeterli bilgi var mı kontrol et
            has_site_info = bool(betting_info) and len(betting_info) > 2
            
            # Tema açıklamalarını tanımla
            theme_descriptions = {
                "sports": "spor bahis fırsatları, canlı maç tahminleri ve yüksek oranlar",
                "casino": "casino oyunları, slot, bakara, poker, rulet ve jackpot fırsatları",
                "promotions": "özel bonuslar, promosyonlar, yatırım bonusları ve üyelik teklifleri",
                "mixed": "karma bahis ve casino içerikleri, genel fırsatlar"
            }
            
            theme_desc = theme_descriptions.get(betting_theme, theme_descriptions["mixed"])
            
            # Site bilgilerinden detayları çıkar
            site_details = ""
            if has_site_info:
                site_name = betting_info.get('site_name', '')
                site_url = betting_info.get('url', '')
                
                site_details = f"""
                Bahis Sitesi: {site_name}
                Site URL: {site_url}
                """
                
                # Bonus bilgilerini ekle
                if 'bonuslar' in betting_info and betting_info['bonuslar']:
                    site_details += "Bonuslar:\n" + "\n".join([f"- {bonus}" for bonus in betting_info['bonuslar']]) + "\n"
                
                # Kampanya bilgilerini ekle
                if 'kampanyalar' in betting_info and betting_info['kampanyalar']:
                    site_details += "Kampanyalar:\n" + "\n".join([f"- {promo}" for promo in betting_info['kampanyalar']]) + "\n"
                
                # PR mesajını ekle
                if 'pr_mesaji' in betting_info and betting_info['pr_mesaji']:
                    site_details += f"PR Mesajı: {betting_info['pr_mesaji'][0]}\n"
            
            prompt = f"""
Hedef: Kullanıcıların kayıt olması ve içeriklerle yoğun etkileşim sağlaması (beğeni, yorum, retweet).

Bu amaçla; gelişmiş analizler, psikolojik manipülasyon teknikleri ve satış odaklı stratejilere dayanarak **{num_tweets} adet profesyonel**, **yüksek dönüşüm odaklı** ve **manipülasyon teknikleri kullanan** bahis/casino promosyon tweeti oluştur.

Tema: {theme_desc}

Site Detayları:
{site_details}

Tweetlerde Kesinlikle Bulunması Gereken Özellikler:

1. **Her tweet 280 karakterden kısa olacak.**
2. **İlk cümlede aşırı dikkat çeken, şok etkisi yaratan bir giriş yapılacak.**
3. **Aciliyet** ve **kıtlık hissi** kuvvetli verilecek ("Son saatler!", "Şu anda Kayıt Olan Kazanıyor!" gibi).
4. **CTA (Harekete Geçirici İfade)** kullanılacak ("Hemen üye ol", "Şansını hemen değerlendir", "Fırsatı kaçırma!" gibi).
5. **Site bağlantısı olarak yalnızca** **"https://cutt.ly/mrlOjHcY"** kullanılacak.
6. **Site adı**, **ilk Kayıt Bonusları** , **özel kayıt ödülleri** ve **İlk Kayıtlara 500 Deneme Bonusu ve 500 Freespin** net şekilde vurgulanacak.
7. **Sadece ilk kayıt olan kullanıcıların** promosyonlardan faydalanabileceği açıkça belirtilecek.
9. **Yüksek kazanç**, **büyük ödüller**, **sınırsız eğlence** duyguları güçlü şekilde tetiklenecek.
10. **Yorum, beğeni ve RT yapanlar** ve **ekstra fırsatlar** mutlaka sunulacak.
11. **Kaybetme korkusu** yaratılacak ("Şimdi kayıt olmazsan fırsatı kaçırırsın!" gibi).
12. **Sosyal kanıt** eklenecek ("Bugün 500 kişi bu etkinlik için kayıt oldu, sırada sen varsın!" gibi).
13. **1-2 etkili emoji** isteğe bağlı olarak kullanılabilir (abartıya kaçmadan).
14. **Kazanç hayali**, **anlık zenginlik arzusu** güçlü şekilde işlenecek.
15. **Beğeni, yorum ve retweet yapanlara ödül fırsatları** belirtilerek etkileşim teşvik edilecek.
16. **Her tweet tamamen benzersiz** olacak, birbirinin tekrarı gibi hissettirmeyecek.
17. **Kayıt olmayanların kaçıracağı fırsatlar** abartılı şekilde vurgulanacak.
18. **Sadece ilk kayıt olanlara özel** kampanya avantajları açıkça belirtilecek.
19. **Deneme Bonusu 500 adet ve Freespin 500 adet olcak şekilde paylaşımlar yapılacak.**

İleri Seviye Manipülasyon Teknikleri:
- **Sınırlı süre / kişi vurgusu** yapılacak ("İlk 200 kişi için geçerli!").
- **Ödüller somutlaştırılacak** ("500 Deneme Bonusu + 500 Freespin!").
- **Topluluk etkisi** oluşturulacak ("10.000'den fazla aktif oyuncu bugün kazandı!").
- **Kayıt olmayanların büyük fırsatları kaçırdığı** psikolojik baskı hissettirilecek.

Çıktı Şartı:
- **Tam olarak {num_tweets} adet tweet** oluşturulacak.
- **Her tweet ayrı bir paragraf olacak.**
- **Her paragraf arasında 2 adet boşluk olacak.**
- **Başka hiçbir açıklama, başlık veya ekstra bilgi eklenmeyecek.**
- **link ekleneceği zaman yalnızca "https://cutt.ly/mrlOjHcY" eklenicek. başka hiç bir link eklenmeyecek!**
"""
            
            # Gemini'den cevap alma
            logger.info(f"[{self.account.username}] Bahis tweet'i oluşturuluyor...")
            response = self.gemini_model.generate_content(prompt)
            
            # Cevabı düzenle ve tweetleri ayır
            generated_text = response.text.strip()
            
            # Cevabı parçalara ayır
            tweets = []
            
            # Satır satır ayırıp tweet formatına getir
            lines = generated_text.split('\n')
            current_tweet = ""
            
            for line in lines:
                line = line.strip()
                # Boş satırları atla
                if not line:
                    if current_tweet:  # Mevcut bir tweet varsa listeye ekle
                        tweets.append(current_tweet)
                        current_tweet = ""
                    continue
                    
                # Numaralandırma ve madde işaretlerini temizle
                line = re.sub(r'^\d+[\.\)]\s*|\-\s*|•\s*', '', line)
                
            #     # Eğer satırda 18+ ve #SorumluBahis var ise muhtemelen tam bir tweet
            #     if '18+' in line and '#Bahis' in line and len(line) > 20:
            #         if current_tweet:  # Önceki tweet varsa ekle
            #             tweets.append(current_tweet)
            #         current_tweet = line  # Yeni tweet başlat
            #     elif current_tweet:  # Mevcut tweete ekleme
            #         current_tweet += " " + line
            #     else:  # Yeni tweet başlat
            #         current_tweet = line
                    
            # # Son tweeti de ekle
            # if current_tweet:
            #     tweets.append(current_tweet)
                
            # # Eğer hala tweet bulunamadıysa, metni doğrudan bölüp düzenleyelim
            # if not tweets and generated_text:
            #     # Metni yaklaşık 240 karakterlik parçalara böl
            #     chars = 240
            #     for i in range(0, len(generated_text), chars):
            #         tweet = generated_text[i:i+chars].strip()
            #         if tweet:
            #             # 18+ ve SorumluBahis eklenmişse ekle
            #             if "18+" not in tweet:
            #                 tweet += " 18+"
            #             if "#SorumluBahis" not in tweet:
            #                 tweet += " #SorumluBahis"
            #             tweets.append(tweet)
            
            # Hâlâ tweet yoksa, varsayılan tweetleri kullan
            tweets = self.generate_tweets(betting_info, has_site_info, tweets)
            
            # Karakter sınırı kontrolü ve istenen sayıda tweet
            valid_tweets = []
            for tweet in tweets:
                if len(tweet) > 280:
                    tweet = tweet[:277] + "..."
                valid_tweets.append(tweet)
                
                if len(valid_tweets) >= num_tweets:
                    break
            
            # Eğer yeterli tweet yoksa ekleme yap
            while len(valid_tweets) < num_tweets:
                idx = len(valid_tweets) % len(tweets)
                valid_tweets.append(tweets[idx])
                
            return valid_tweets[:num_tweets]
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Bahis tweet'i oluşturma hatası: {e}")
            # Hata durumunda varsayılan tweet'ler
            return [
                "🔥 Bugünün en yüksek oranlı maçları burada! Hemen üye ol, ilk yatırımına %100 bonus kazan! [Link] 18+ #SorumluBahis",
                "🎰 Hafta sonu jackpot fırsatı! 50.000 TL'lik büyük ödül seni bekliyor. Hemen katıl, şansını dene! [Link] 18+ #Casino #SorumluBahis",
                "⚽ Akşamın maçları için canlı bahis heyecanı başlıyor! Yüksek oranlar ve özel promosyonlar için tıkla! [Link] 18+ #SorumluBahis"
            ][:num_tweets]

    def generate_tweets(self, betting_info, has_site_info, tweets):
        if not tweets:
            # Bahis bilgilerini txt dosyasından yükle
            betting_info = self.load_betting_site_info()
            has_site_info = bool(betting_info) and len(betting_info) > 2

            if has_site_info:
                site_name = betting_info.get('site_name', 'sitemiz')
                bonus_info = betting_info.get('bonuslar', [])
                promotions = betting_info.get('kampanyalar', [])
                pr_message = betting_info.get('pr_mesaji', [""]).pop(0) if betting_info.get('pr_mesaji') else ""

                # Bonus ve promosyon bilgilerini birleştir
                bonus_text = f"Bonuslar: {', '.join(bonus_info)}" if bonus_info else ""
                promo_text = f"Kampanyalar: {', '.join(promotions)}" if promotions else ""

                tweets = [
                    f"🔥 {site_name}'de bugünün en yüksek oranlı maçları burada! {bonus_text} Hemen üye ol, ilk yatırımına %100 bonus kazan! [Link] 18+ #SorumluBahis",
                    f"🎰 {site_name} hafta sonu jackpot fırsatı! 50.000 TL'lik büyük ödül seni bekliyor. {promo_text} Hemen katıl, şansını dene! [Link] 18+ #Casino #SorumluBahis",
                    f"⚽ {site_name}'de akşamın maçları için canlı bahis heyecanı başlıyor! {pr_message} Yüksek oranlar ve özel promosyonlar için tıkla! [Link] 18+ #SorumluBahis"
                ]
            else:
                # Site bilgisi yoksa varsayılan tweetler
                tweets = [
                    "🔥 Bugünün en yüksek oranlı maçları burada! Hemen üye ol, ilk yatırımına %100 bonus kazan! [Link] 18+ #SorumluBahis",
                    "🎰 Hafta sonu jackpot fırsatı! 50.000 TL'lik büyük ödül seni bekliyor. Hemen katıl, şansını dene! [Link] 18+ #Casino #SorumluBahis",
                    "⚽ Akşamın maçları için canlı bahis heyecanı başlıyor! Yüksek oranlar ve özel promosyonlar için tıkla! [Link] 18+ #SorumluBahis"
                ]

        return tweets
        
        
    def analyze_past_engagement(self):
        """
        Geçmiş bahis tweet'lerinin performansını analiz eder
        
        :return: Performans metrikleri sözlüğü
        """
        try:
            # Analiz sonuçları için dizin oluştur
            analysis_dir = Path("engagement_analysis")
            analysis_dir.mkdir(exist_ok=True)
            
            # Analiz dosyasının yolu
            analysis_file = analysis_dir / f"{self.account.username}_betting_engagement.json"
            
            # Mevcut analiz verilerini yükle
            analysis_data = {
                "last_updated": datetime.now().isoformat(),
                "top_tweets": [],
                "effective_hashtags": [],
                "optimal_times": [],
                "content_preferences": {}
            }
            
            if analysis_file.exists():
                with open(analysis_file, 'r', encoding='utf-8') as f:
                    try:
                        analysis_data = json.load(f)
                    except json.JSONDecodeError:
                        pass
            
            # Gemini AI kullanarak tweet performansını analiz et
            if hasattr(self, 'tweets_data') and self.tweets_data:
                # Son 20 tweet'i seç
                recent_tweets = self.tweets_data[-20:]
                
                # Gemini AI'a analiz için gönder
                analysis_prompt = f"""
                Aşağıdaki bahis ve casino tweet'lerini analiz ederek en etkili olan tweet tarzını belirle:
                
                Tweet Verileri:
                {json.dumps(recent_tweets, ensure_ascii=False, indent=2)}
                
                Çıktı formatı (JSON):
                {{
                    "top_performing_style": "En etkili tweet tarzı açıklaması",
                    "best_hashtags": ["en", "etkili", "hashtagler"],
                    "optimal_posting_times": ["en", "iyi", "paylaşım", "zamanları"],
                    "content_preferences": {{"casino": yüzde, "sports": yüzde, "promotions": yüzde}}
                }}
                """
                
                try:
                    analysis_response = self.gemini_model.generate_content(analysis_prompt)
                    analysis_result = json.loads(analysis_response.text)
                    
                    # Analiz sonuçlarını güncelle
                    if 'best_hashtags' in analysis_result:
                        analysis_data['effective_hashtags'] = analysis_result['best_hashtags']
                    
                    if 'optimal_posting_times' in analysis_result:
                        analysis_data['optimal_times'] = analysis_result['optimal_posting_times']
                    
                    if 'content_preferences' in analysis_result:
                        analysis_data['content_preferences'] = analysis_result['content_preferences']
                    
                except Exception as e:
                    logger.warning(f"[{self.account.username}] AI tweet analizi yapılamadı: {e}")
            
            # Analiz verilerini kaydet
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump(analysis_data, f, ensure_ascii=False, indent=2)
            
            return analysis_data
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Tweet performans analizi hatası: {e}")
            return {
                "top_tweets": [
                    "🔥 Bugünün en yüksek oranlı maçları burada! Hemen üye ol, ilk yatırımına %100 bonus kazan!",
                    "⚽ Canlı bahiste şampiyonlar burada! Maç başlıyor, sen de yerini al!",
                    "🎰 Jackpot alarmı! Bu hafta 500.000 TL'lik mega ödül seni bekliyor!"
                ],
                "effective_hashtags": ["#Bahis", "#Casino", "#Bonus", "#Jackpot", "#SporBahis"],
                "optimal_times": ["19:00-22:00", "12:00-14:00", "Hafta sonu akşamları"]
            }
            
    def manage_session(self, action: str) -> bool:
        """
        Tarayıcı oturumunu yönetir. Kaydetme ve yükleme işlemleri yapar.

        :param action: 'save' veya 'load' işlemi
        :return: İşlem başarılı mı
        """
        try:
            if action == 'save':
                # Çerezleri kaydetme
                pickle.dump(self.driver.get_cookies(),
                            open(self.session_path, "wb"))
                logger.info(f"[{self.account.username}] Oturum kaydedildi")
                return True
            elif action == 'load':
                # Oturum dosyası yoksa False döner
                if not self.session_path.exists():
                    return False

                # Twitter ana sayfasını aç
                self.driver.get("https://twitter.com")

                # Kayıtlı çerezleri yükle
                cookies = pickle.load(open(self.session_path, "rb"))
                for cookie in cookies:
                    self.driver.add_cookie(cookie)

                # Sayfayı yenile
                self.driver.refresh()
                time.sleep(5)
                
                # Çerezlerin başarıyla yüklendiğini doğrula
                try:
                    # Giriş butonu görünüyorsa oturum aktif değil
                    login_buttons = self.driver.find_elements(By.XPATH, "//a[@data-testid='login']")
                    if login_buttons:
                        logger.warning(f"[{self.account.username}] Oturum geçersiz: Giriş sayfası görüntülendi")
                        return False
                    return True
                except Exception:
                    # Buton bulunamazsa muhtemelen oturum aktif
                    return True
        except Exception as e:
            logger.error(
                f"[{self.account.username}] Oturum {action} hatası: {e}")
            return False

    @smart_retry
    def login(self) -> bool:
        """
        Twitter hesabına giriş yapar.

        :return: Giriş başarılı mı
        """
        try:
            # Kayıtlı oturumu yüklemeyi dene
            if self.manage_session('load'):
                try:
                    # Giriş kontrolü
                    self.wait.until(EC.presence_of_element_located(
                        (By.XPATH, "//a[@href='/compose/post']")))
                    logger.info(
                        f"[{self.account.username}] Oturum girişi başarılı!")
                    return True
                except TimeoutException:
                    logger.info(
                        f"[{self.account.username}] Oturum süresi doldu, yeni giriş yapılacak")

            # Giriş sayfasını aç
            self.driver.get("https://twitter.com/i/flow/login")
            time.sleep(5)

            # Kullanıcı adı girişi
            if not self.safe_action('type', (By.NAME, "text"), self.account.username):
                return False

            # Sonraki adıma geç
            if not self.safe_action('click', (By.XPATH, "//div[contains(@class,'css-175oi2r r-1mmae3n')]/following-sibling::button[1]")):
                return False

            # Şifre girişi
            if not self.safe_action('type', (By.NAME, "password"), self.account.password):
                return False

            # Giriş butonuna tıkla
            if not self.safe_action('click', (By.XPATH, "//div[@class='css-175oi2r r-b9tw7p']//button[1]")):
                return False

            time.sleep(3)

            # Giriş kontrolü
            try:
                post_button = self.wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//a[@href='/compose/post']")))
                
                # Oturumu kaydet
                self.manage_session('save')
                logger.info(f"[{self.account.username}] Giriş başarılı!")
                return True
            except TimeoutException:
                # Telefon veya e-posta doğrulama kontrolü
                try:
                    verify_element = self.driver.find_element(By.XPATH, "//span[contains(text(), 'Hesabını doğrula') or contains(text(), 'Verify') or contains(text(), 'Enter your phone')]")
                    if verify_element:
                        logger.error(f"[{self.account.username}] Hesap doğrulama gerekiyor, manuel giriş yapılmalı")
                        return False
                except Exception:
                    pass
                
                logger.error(f"[{self.account.username}] Giriş yapılamadı, tweet butonu bulunamadı")
                return False

        except Exception as e:
            logger.error(f"[{self.account.username}] Giriş başarısız: {e}")
            return False

    def safe_action(
        self,
        action_type: str,
        locator: Tuple[By, str],
        value: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[Union[bool, WebElement]]:
        """
        Öğeler üzerinde güvenli eylem gerçekleştirir.

        :param action_type: Eylem türü ('click' veya 'type')
        :param locator: Öğenin bulunma yöntemi
        :param value: Yazılacak metin (type eylemi için)
        :param description: Eylem açıklaması
        :return: Eylem sonucu
        """
        max_attempts = 3
        attempt = 0
        
        while attempt < max_attempts:
            try:
                # Element görünür olana kadar bekle
                element = self.wait.until(EC.visibility_of_element_located(locator))

                if action_type == 'click':
                    # Scroll to element first to ensure visibility
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.5)  # Scroll işleminin tamamlanması için bekle
                    
                    # Try standard click first
                    try:
                        element.click()
                    except Exception:
                        # If standard click fails, try JavaScript click
                        self.driver.execute_script("arguments[0].click();", element)
                        
                    logger.info(
                        f"[{self.account.username}] Butona Tıkladı {description or locator[1]}")
                    return True

                elif action_type == 'type':
                    # Clear field first
                    element.clear()
                    
                    # Type with small delay between characters to mimic human typing
                    for char in value:
                        element.send_keys(char)
                        time.sleep(random.uniform(0.01, 0.05))  # Küçük rastgele gecikme
                        
                    logger.info(
                        f"[{self.account.username}] Yazdı {description or locator[1]}")
                    return True

                return element

            except TimeoutException:
                attempt += 1
                logger.warning(
                    f"[{self.account.username}] Zaman aşımı ({attempt}/{max_attempts}): {action_type} {description or locator[1]}")
                
                # Try different approach if element not found
                try:
                    # Scroll down a bit and try again
                    self.driver.execute_script("window.scrollBy(0, 100);")
                    time.sleep(1)
                except Exception:
                    pass
                    
            except StaleElementReferenceException:
                attempt += 1
                logger.warning(
                    f"[{self.account.username}] Element artık geçerli değil ({attempt}/{max_attempts}): {action_type} {description or locator[1]}")
                time.sleep(1)  # Sayfanın yenilenmesi için bekle
                
            except ElementNotInteractableException:
                attempt += 1
                logger.warning(
                    f"[{self.account.username}] Element etkileşime geçilemiyor ({attempt}/{max_attempts}): {action_type} {description or locator[1]}")
                # Try to scroll element into view
                try:
                    element = self.driver.find_element(*locator)
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", element)
                    time.sleep(1)
                except Exception:
                    pass
                    
            except Exception as e:
                attempt += 1
                logger.warning(
                    f"[{self.account.username}] Eylem sırasında hata ({attempt}/{max_attempts}): {e}")
                time.sleep(1)
        
        logger.error(
            f"[{self.account.username}] Maksimum deneme sayısı aşıldı: {action_type} {description or locator[1]}")
        return None
    
    

    def get_random_image(self, image_dir: Optional[str] = None, exclude_used: bool = True) -> Optional[str]:
        """Geliştirilmiş rastgele görsel seçme fonksiyonu - daha önce kullanılmış görselleri kullanmaz"""
        try:
            # Eğer henüz tanımlanmamışsa, sınıfa used_images listesi ekle
            if not hasattr(self, 'used_images'):
                self.used_images = []
            
            # Varsayılan görsel dizini ayarla
            if not image_dir:
                # Önce çalışma dizininde "images" klasörünü kontrol et
                current_dir = os.path.dirname(os.path.abspath(__file__))
                image_dir = os.path.join(current_dir, "images")
                
                # Eğer bu dizin yoksa, çalışma dizininin kendisinde "images" klasörünü dene
                if not os.path.exists(image_dir):
                    image_dir = os.path.join(os.getcwd(), "images")
                    
                # Hala bulunamadıysa, özel konumları dene
                if not os.path.exists(image_dir):
                    # Windows ve macOS için farklı yolları dene
                    if os.name == 'nt':  # Windows
                        possible_dirs = [
                            "C:\\Users\\Administrator\\Desktop\\casino_images",
                            os.path.join(os.path.expanduser("~"), "Desktop", "images"),
                            os.path.join(os.path.expanduser("~"), "Pictures", "twitter_images")
                        ]
                    else:  # macOS/Linux
                        possible_dirs = [
                            "/Users/tahaturkdil/Desktop/GÖRSELLER/casino_images",
                            os.path.join(os.path.expanduser("~"), "Desktop", "images"),
                            os.path.join(os.path.expanduser("~"), "Pictures", "twitter_images")
                        ]
                    
                    # Olası dizinleri kontrol et
                    for dir_path in possible_dirs:
                        if os.path.exists(dir_path):
                            image_dir = dir_path
                            break

            # Dizin kontrolü
            if not os.path.exists(image_dir):
                logger.warning(f"[{self.account.username}] Görsel dizini bulunamadı: {image_dir}")
                
                # Yedek olarak bot dizininde images klasörü oluştur
                fallback_dir = os.path.join(os.getcwd(), "images")
                try:
                    if not os.path.exists(fallback_dir):
                        os.makedirs(fallback_dir)
                        logger.info(f"[{self.account.username}] Görsel dizini oluşturuldu: {fallback_dir}")
                    image_dir = fallback_dir
                except Exception as e:
                    logger.error(f"[{self.account.username}] Yedek dizin oluşturma hatası: {e}")
                    return None
            
            # Dizin erişim kontrolü
            if not os.access(image_dir, os.R_OK):
                logger.error(f"[{self.account.username}] Görsel dizinine okuma izni yok: {image_dir}")
                return None
                
            logger.info(f"[{self.account.username}] Görsel dizini: {image_dir}")

            # İzin verilen görsel uzantıları
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.mp4', '.heic', '.mov'}

            # Tüm uygun görselleri bul
            available_images = []
            try:
                for file in os.listdir(image_dir):
                    file_path = os.path.join(image_dir, file)
                    if os.path.isfile(file_path):  # Sadece dosyaları kontrol et
                        ext = os.path.splitext(file)[1].lower()
                        if ext in allowed_extensions:
                            # Dosya boyutu kontrolü (boş dosyaları atla)
                            if os.path.getsize(file_path) > 0:
                                # Dosya erişim kontrolü
                                if os.access(file_path, os.R_OK):
                                    available_images.append(file_path)
                                else:
                                    logger.warning(f"[{self.account.username}] Dosyaya erişim izni yok: {file}")
                            else:
                                logger.warning(f"[{self.account.username}] Boş dosya atlanıyor: {file}")
            except Exception as e:
                logger.error(f"[{self.account.username}] Dizin listeleme hatası: {e}")
                return None

            # Bulunan görselleri logla
            logger.info(f"[{self.account.username}] Toplam {len(available_images)} kullanılabilir görsel bulundu")

            if not available_images:
                logger.warning(f"[{self.account.username}] Klasörde kullanılabilir görsel bulunamadı: {image_dir}")
                return None
            
            # Daha önce kullanılmamış görselleri filtrele
            if exclude_used and len(self.used_images) < len(available_images):
                unused_images = [img for img in available_images if img not in self.used_images]
                
                # Eğer kullanılmamış görsel kalmadıysa, used_images'i temizle
                if not unused_images:
                    logger.info(f"[{self.account.username}] Tüm görseller kullanıldı. Liste sıfırlanıyor.")
                    self.used_images = []
                    unused_images = available_images
            else:
                unused_images = available_images

            # Rastgele bir görsel seç
            selected_image = random.choice(unused_images)
            
            # Seçilen görselin varlığını ve erişilebilirliğini son kez kontrol et
            if not os.path.exists(selected_image):
                logger.error(f"[{self.account.username}] Seçilen görsel bulunamadı: {selected_image}")
                return None
                
            if not os.access(selected_image, os.R_OK):
                logger.error(f"[{self.account.username}] Seçilen görsele erişim izni yok: {selected_image}")
                return None
            
            # Kullanılan görseli listeye ekle
            if exclude_used:
                self.used_images.append(selected_image)
            
            logger.info(f"[{self.account.username}] Görsel seçildi: {os.path.basename(selected_image)}")
            logger.info(f"[{self.account.username}] Görsel tam yolu: {selected_image}")
            
            # Dosya boyutunu logla
            file_size_mb = os.path.getsize(selected_image) / (1024 * 1024)
            logger.info(f"[{self.account.username}] Görsel boyutu: {file_size_mb:.2f} MB")
            
            return selected_image

        except Exception as e:
            logger.error(f"[{self.account.username}] Görsel seçme hatası: {e}")
            import traceback
            logger.error(f"[{self.account.username}] Hata detayı: {traceback.format_exc()}")
            return None
        
        
    logger = logging.getLogger(__name__)

    def post_contest_tweet(self, hashtags: List[str] = ["#Bahis", "#AloBet"], reward_count: int = 1, event: Optional[str] = None, use_poll: bool = False) -> bool:
        """
        Gemini AI ile kupon paylaşımı temalı yarışma tweet'i oluşturur ve gönderir.
        Katılım şartı: Retweet (RT), takip etme ve kupon ekran görüntüsü yorumda paylaşma.
        Ödüller: AloBet'te 100 TL Spor Bonusu, 300 TL Nakit Deneme Bonusu veya 300 Free Spin.
        
        Args:
            hashtags (list): Kullanılacak hashtag'ler.
            reward_count (int): Kaç kazanan seçileceği (varsayılan 1).
        
        Returns:
            bool: Tweet gönderimi başarılıysa True, değilse False.
        """
        try:
            # Ödül türleri
            rewards = [
                "100 TL Spor Bonusu",
                "300 TL Nakit Deneme Bonusu",
                "300 Free Spin"
            ]
            
            # Ödül metni
            reward_text = rewards[0] if reward_count == 1 else f"veya {', '.join(rewards)}"
            
            # Gemini AI için dinamik prompt
            prompt = (
                f"Bahis/casino nişine uygun, kupon paylaşımı temalı bir yarışma tweet'i yaz. "
                f"Kullanıcıları bu hafta yaptıkları bahis kuponlarının ekran görüntüsünü yoruma paylaşmaya teşvik et. "
                f"Katılım şartı olarak tweet'i retweet (RT) yapmalarını, hesabı takip etmelerini ve "
                f"yorumda kupon ekran görüntüsü paylaşmalarını belirt. "
                f"Ödül olarak AloBet'te {reward_text} sun, kazanan kuponu tutanlar arasından seçilecek. "
                f"280 karakterden kısa, {' '.join(hashtags)} kullan. "
                f"Örnek: '🏆 Haftanın kupon yarışması! Bu hafta kuponunu yoruma ekran görüntüsüyle at, "
                f"RT yap, takip et, tutan kupon AloBet'te 100 TL Spor Bonusu kazanır! #Bahis #AloBet'"
            )
            
            # Gemini AI ile içerik üret
            tweet_content = self.gemini_model.generate_content(prompt)
            if not tweet_content or len(tweet_content) > 280:
                logger.error("Geçersiz veya uzun tweet içeriği üretildi")
                return False
            
            # Görsel seçimi
            image_paths = [
                "alobet_bonus.jpg",
            ]
            image_path = random.choice(image_paths) if random.random() < 0.9 else None  # %90 görsel ekle
            
            # Tweet gönder
            success = self.post_tweet(tweet_content, image_path=image_path)
            if success:
                logger.info(f"{self.username}: Kupon yarışma tweet'i gönderildi: {tweet_content}")
                # Tweet URL'sini kaydet
                self.driver.get(f"https://x.com/{self.username}")
                time.sleep(random.uniform(1, 2))
                latest_tweet = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='tweet']")
                tweet_url = latest_tweet.find_element(By.CSS_SELECTOR, "a").get_attribute("href")
                self.activities['contest_tweet']['url'] = tweet_url
            else:
                logger.error(f"{self.username}: Kupon yarışma tweet'i gönderilemedi")
            
            return success
        
        except Exception as e:
            logger.error(f"Kupon yarışma tweet'i gönderilirken hata: {str(e)}")
            return False
    
    

    def clean_tweet_text(self, text):
        """
        Tweet metnini ChromeDriver ile uyumlu hale getirir
        
        :param text: Orijinal tweet metni
        :return: Temizlenmiş tweet metni
        """
        try:
            # Sadece ASCII karakterlerini ve temel Türkçe karakterleri tut
            cleaned_text = ''.join(
                char for char in text 
                if ord(char) < 128 or  # ASCII karakterleri
                char in 'şŞçÇğĞıİöÖüÜ'  # Türkçe karakterler
            )
            
            # Boşlukları düzenle (birden fazla boşluğu tek boşluğa indirger)
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
            
            # Emoji ve diğer özel karakterleri kaldır
            #cleaned_text = cleaned_text.encode('ascii', 'ignore').decode('ascii')
            
            return cleaned_text.strip()
        
        except Exception as e:
            logger.warning(f"Tweet metni temizleme hatası: {e}")
            return text

    @smart_retry
    def post_tweet(self, message: str, include_image: bool = True) -> bool:
        if message in self.posted_tweets:
            logger.warning(f"[{self.account.username}] Bu tweet daha önce paylaşıldı: {message[:50]}...")
            return False
        ...
        self.posted_tweets.add(message)
        ...
        """
        Tweet gönderir.
        Varsayılan olarak %90 ihtimalle görselli, %10 ihtimalle görselsiz tweet paylaşır.

        :param message: Gönderilecek tweet metni
        :param include_image: Görsel eklensin mi
        :return: Tweet gönderimi başarılı mı
        """
        max_retries = 3
        retry_count = 0

        # Görsel ekleme kararını rastgele belirle (varsayılan olarak True gelse bile)
        if include_image and random.random() < 0.0:  # %10 ihtimalle görseli devre dışı bırak - 0.1
            include_image = False

        # Tweet metnini temizle
        cleaned_message = self.clean_tweet_text(message)

        logger.info(f"[{self.account.username}] Ana sayfaya yönlendiriliyor")
        self.driver.get("https://x.com/home?mx=2")
        time.sleep(5)

        while retry_count < max_retries:
            try:
                # Tweet oluşturma butonuna tıkla
                if not self.safe_action('click', (By.XPATH, "//a[@href='/compose/post']")):
                    retry_count += 1
                    continue

                time.sleep(5)

                # Görsel yükleme
                if include_image:
                    try:
                        element = WebDriverWait(self.driver, 15).until(
                            EC.element_to_be_clickable(
                                (By.XPATH, "//div[contains(@class,'css-175oi2r r-1pi2tsx')]//button"))
                        )
                        self.driver.execute_script(
                            "arguments[0].click();", element)
                        time.sleep(2)

                        # Görsel girişi
                        image_input = self.driver.find_element(
                            By.XPATH, "//input[@data-testid='fileInput']")
                        image_path = self.get_random_image(exclude_used=True)
                        if image_path:
                            image_input.send_keys(image_path)
                            time.sleep(10)  # Görsel yüklenmesi için bekle
                            logger.info(
                                f"[{self.account.username}] Görselli tweet paylaşılıyor")
                        else:
                            include_image = False
                            logger.warning(f"[{self.account.username}] Görsel bulunamadı, görselsiz devam ediliyor")
                    except Exception as e:
                        logger.warning(
                            f"[{self.account.username}] Görsel yükleme hatası: {e}")
                        include_image = False

                # Tweet metni girişi
                tweet_box = self.wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//div[@data-testid='tweetTextarea_0']")
                ))
                
                # Metni insan gibi daha doğal girme
                self.driver.execute_script("arguments[0].focus();", tweet_box)
                
                # Her karakteri ayrı ayrı ve hafif gecikmeyle gönder
                for char in cleaned_message:
                    tweet_box.send_keys(char)
                    time.sleep(random.uniform(0.01, 0.03))  # Rastgele küçük gecikmeler

                # Post butonunu bulma ve tıklama stratejileri
                post_button_xpaths = [
                    "(//span[text()='Post'])[1]/ancestor::button",
                    "//div[contains(@class, 'r-pw2am6')]/descendant::span[contains(text(), 'Post')]/ancestor::div[@role='button']",
                    "//div[contains(@class, 'css-175oi2r')]/div/span[contains(text(), 'Post')]/ancestor::div[@role='button']"
                ]
                
                post_clicked = False
                for xpath in post_button_xpaths:
                    try:
                        post_button = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, xpath))
                        )
                        self.driver.execute_script("arguments[0].click();", post_button)
                        post_clicked = True
                        break
                    except Exception:
                        continue
                
                if not post_clicked:
                    raise Exception("Tweet post butonu bulunamadı")

                # Tweet'in gönderilmesini bekle
                time.sleep(5)
                
                # Tweet başarıyla gönderildi mi kontrol et
                try:
                    # Başarı mesajı veya yeni tweet'in görüntülenmesi
                    success_element = self.driver.find_element(By.XPATH, "//div[contains(text(), 'Your post was sent') or contains(@aria-label, 'Timeline')]")
                    if success_element:
                        image_status = "görselli" if include_image else "görselsiz"
                        logger.info(
                            f"[{self.account.username}] {image_status} tweet başarıyla gönderildi")
                        return True
                except Exception:
                    # Başarı mesajı bulunamadı, ancak yine de başarılı olabilir
                    logger.info(f"[{self.account.username}] Tweet gönderildi, ancak başarı mesajı görülmedi")
                    return True

            except Exception as e:
                logger.error(
                    f"[{self.account.username}] Tweet gönderme denemesi {retry_count + 1} başarısız: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(5)
                    self.driver.refresh()
                    time.sleep(2)

        logger.error(
            f"[{self.account.username}] Maksimum deneme sayısına rağmen tweet gönderilemedi")
        return False
    
    def find_all_posts(self):
        """
        Twitter ana sayfasındaki tüm postları bulur.
        Çeşitli XPath stratejileri kullanarak maksimum sayıda post bulur.

        :return: Bulunan postlar listesi
        """
        # Tüm olası post XPath'leri
        post_xpaths = [
            "//article[@data-testid='tweet']",  # Belirtilen tweet XPath'i
            # Standart tweet yapısı
            "//article[contains(@class,'css-175oi2r r-18u37iz')]",
            # Hücre içindeki makaleler
            "//div[@data-testid='cellInnerDiv']//article",
            # CSS sınıfına göre
            "//div[contains(@class,'css-175oi2r r-aqfbo4')]//article",
            # Daha geniş CSS sınıfı
            "//div[contains(@class,'css-175oi2r')]//article",
            "//div[@data-testid='cellInnerDiv']",  # Hücre iç div'leri
            "//div[contains(@class,'r-1867qdf')]//article"  # Alternatif sınıf
        ]

        all_posts = []

        # Her bir XPath'i dene ve benzersiz postları topla
        for xpath in post_xpaths:
            try:
                found_posts = self.driver.find_elements(By.XPATH, xpath)
                if found_posts:
                    for post in found_posts:
                        # Post zaten listeye eklenmemişse ekle
                        if post not in all_posts:
                            all_posts.append(post)
                    logger.info(
                        f"[{self.account.username}] '{xpath}' ile {len(found_posts)} gönderi bulundu")
            except Exception as e:
                logger.debug(
                    f"[{self.account.username}] XPath ile post arama hatası: {xpath} - {str(e)}")

        # Sonuçları logla
        if all_posts:
            logger.info(
                f"[{self.account.username}] Toplam {len(all_posts)} benzersiz post bulundu")
        else:
            logger.warning(f"[{self.account.username}] Hiç post bulunamadı")

        return all_posts

    def get_tweet_content(self, post_element):
        """
        Tweet içeriğini (metin ve görsel bilgisi) çeker

        :param post_element: Tweet elementi
        :return: (tweet_text, has_image, image_description)
        """
        # Tweet metnini çek
        tweet_text = ""
        try:
            text_element = post_element.find_element(
                By.XPATH, ".//div[@data-testid='tweetText']")
            if text_element:
                tweet_text = text_element.text
        except:
            try:
                # Alternatif XPath ile deneme
                text_elements = post_element.find_elements(
                    By.XPATH, ".//div[contains(@class, 'css-901oao')]")
                for elem in text_elements:
                    if elem.text and len(elem.text) > 10:  # En az 10 karakter
                        tweet_text = elem.text
                        break
            except:
                pass

        # Görsel kontrolü
        has_image = False
        image_description = ""
        try:
            # Tweet'de görsel var mı kontrol et - belirtilen XPath'i kullan
            image_elements = post_element.find_elements(
                By.XPATH, ".//img[@alt='Image']")

            # Alternatif görsel XPath'leri
            if not image_elements:
                image_elements = post_element.find_elements(
                    By.XPATH, ".//div[contains(@class,'css-175oi2r r-1ets6dv')]")

            if image_elements and len(image_elements) > 0:
                has_image = True

                # Görsel alt metni veya tanımını almaya çalış
                try:
                    alt_text = image_elements[0].get_attribute(
                        "aria-label") or image_elements[0].get_attribute("alt") or ""
                    if alt_text:
                        image_description = alt_text
                    else:
                        # Görsel türünü belirle
                        if "photo" in image_elements[0].get_attribute("class").lower():
                            image_description = "bir fotoğraf"
                        elif "video" in image_elements[0].get_attribute("class").lower():
                            image_description = "bir video"
                        else:
                            image_description = "bir görsel"
                except:
                    image_description = "bir görsel"

                # Görsel içeriğini temel seviyede analiz et
                try:
                    # Görsel boyutunu analiz et
                    img_width = image_elements[0].size['width']
                    img_height = image_elements[0].size['height']

                    # Boy/en oranına göre görsel türünü tahmin et
                    if img_width > img_height * 1.5:
                        image_description += " (geniş açı)"
                    elif img_height > img_width * 1.5:
                        image_description += " (dikey çekim)"
                except:
                    pass

        except Exception as e:
            logger.debug(
                f"[{self.account.username}] Görsel analizi hatası: {e}")

        return tweet_text, has_image, image_description

    def get_tweet_url(self, post_element):
        """
        Tweet URL'ini al

        :param post_element: Tweet elementi
        :return: Tweet URL'i veya boş string
        """
        try:
            url_element = post_element.find_element(By.XPATH, ".//a[contains(@href, '/status/')]")
            url = url_element.get_attribute("href")
            if url and '/status/' in url:
                # "/analytics" kısmını URL'den kaldır
                if "/analytics" in url:
                    url = url.split("/analytics")[0]
                return url
            return ""
        except Exception:
            return ""

    def get_tweet_date(self, post_element):
        """
        Tweet paylaşım tarihini alır

        :param post_element: Tweet elementi
        :return: Tweet paylaşım tarihi (metin) veya None eğer tarih bulunamazsa
        """
        try:
            # Belirtilen XPath ile tweet tarihini bul
            time_element = post_element.find_element(
                By.XPATH, ".//a[@role='link']//time")

            if time_element:
                # Zaman bilgisini al
                datetime_str = time_element.get_attribute("datetime")
                # Görünen tarih metnini al (örn: "2s", "1h", "Apr 2")
                display_date = time_element.text

                logger.debug(
                    f"[{self.account.username}] Tweet tarihi: {datetime_str}, Görünen: {display_date}")
                return {
                    "datetime": datetime_str,
                    "display_date": display_date
                }

            return None
        except Exception as e:
            logger.debug(
                f"[{self.account.username}] Tweet tarihi alınamadı: {e}")
            return None


    def get_interaction_count(self, post_element, index):
        """
        Belirli bir etkileşim sayısını almak için yardımcı fonksiyon
        
        :param post_element: Tweet elementi
        :param index: Etkileşim tipi indeksi:
            1: Yorumlar, 2: Yeniden paylaşımlar, 3: Beğeniler, 4: Görüntülemeler
        :return: Etkileşim sayısı ya da 0
        """
        try:
            # Verilen XPath'i kullan
            xpath = f"(//span[contains(@class,'css-1jxf684 r-1ttztb7')])[{index}]"
            
            try:
                # Önce global arama yap
                interaction_element = self.driver.find_element(By.XPATH, xpath)
                count_text = interaction_element.text.strip()
                if count_text:
                    return self.parse_count(count_text)
            except:
                # Eğer global arama başarısız olursa, post elementi içinde ara
                try:
                    relative_xpath = f".//span[contains(@class,'css-1jxf684 r-1ttztb7')]"
                    elements = post_element.find_elements(By.XPATH, relative_xpath)
                    
                    # Eğer yeterli sayıda element varsa ve belirtilen indeks mevcutsa
                    if elements and len(elements) >= index:
                        count_text = elements[index-1].text.strip()
                        if count_text:
                            return self.parse_count(count_text)
                except:
                    pass
            
            # Hiçbir şekilde bulunamadıysa varsayılan değeri döndür
            logger.debug(f"[{self.account.username}] Etkileşim sayısı bulunamadı (İndeks: {index})")
            return 1  # Varsayılan değer
            
        except Exception as e:
            logger.debug(f"[{self.account.username}] Etkileşim sayısı alma hatası: {str(e)}")
            return 1  # Hata durumunda varsayılan değer
    
    def parse_count(self, count_text: str) -> int:
        """
        Sayı metnini sayısal değere dönüştürür (K, M gibi kısaltmaları işler)

        :param count_text: Sayı metni (örn: "1.5K", "2M")
        :return: Sayısal değer
        """
        if not count_text or count_text.strip() == "":
            return 0

        count_text = count_text.strip().replace(",", ".")

        try:
            # K (bin) ve M (milyon) kısaltmalarını işle
            if 'K' in count_text or 'k' in count_text:
                multiplier = 1000
                count_text = count_text.replace('K', '').replace('k', '')
                return int(float(count_text) * multiplier)
            elif 'M' in count_text or 'm' in count_text:
                multiplier = 1000000
                count_text = count_text.replace('M', '').replace('m', '')
                return int(float(count_text) * multiplier)
            elif 'B' in count_text or 'b' in count_text:  # Milyar
                multiplier = 1000000000
                count_text = count_text.replace('B', '').replace('b', '')
                return int(float(count_text) * multiplier)
            elif count_text.replace('.', '').isdigit():
                return int(float(count_text))
            else:
                return 0
        except Exception:
            return 0
        
        
    def calculate_post_score(self, post_element):
        """
        Gönderinin etkileşim skorunu hesaplar.
        Daha kapsamlı etkileşim analizi yapar.

        :param post_element: Tweet elementi
        :return: Hesaplanan etkileşim skoru
        """
        try:
            # Temel metrikleri al - minimum 1 değeri garantile
            comment_count = max(1, self.get_interaction_count(post_element, 1))
            retweet_count = max(1, self.get_interaction_count(post_element, 2))
            like_count = max(1, self.get_interaction_count(post_element, 3))
            view_count = max(1, self.get_interaction_count(post_element, 4))

            # Gönderi metnini analiz et
            post_text = ""
            try:
                text_elements = post_element.find_elements(
                    By.XPATH, ".//div[@data-testid='tweetText']")
                if text_elements:
                    post_text = text_elements[0].text.lower()
            except Exception:
                pass
                
            # Bahis/Casino bağlantılı kelime analizi
            betting_keywords = [
                'bahis', 'casino', 'slot', 'bonus', 'jackpot', 'rulet', 'blackjack', 'poker',
                'free spin', 'bet', 'odds', 'oranlar', 'maç', 'kupon', 'iddaa', 
                'kazanç', 'para', 'kazandır', 'fırsat', 'promosyon', 'futbol', 'kupon'
            ]
            
            keyword_count = 0
            for keyword in betting_keywords:
                if keyword in post_text.lower():
                    keyword_count += 1
            
            # Bahis içerik bonusu - bahis içerikli postlara daha fazla ağırlık ver
            betting_content_bonus = min(15, keyword_count * 3)

            # Gönderinin sahip olduğu medya türünü kontrol et
            has_image = False
            has_video = False

            try:
                # Çeşitli media selektörlerini dene
                media_selectors = [
                    ".//img[@alt='Image']",  # Belirtilen XPath
                    ".//div[@data-testid='tweetPhoto']",
                    ".//img[contains(@src, 'https://pbs.twimg.com/media/')]",
                    ".//div[contains(@class, 'r-1p0dtai')]//img"
                ]

                video_selectors = [
                    ".//div[@data-testid='videoPlayer']",
                    ".//video",
                    ".//div[contains(@class, 'r-1awozwy')]/div[contains(@class, 'r-1p0dtai')]"
                ]

                for selector in media_selectors:
                    elements = post_element.find_elements(By.XPATH, selector)
                    if elements and len(elements) > 0:
                        has_image = True
                        break

                for selector in video_selectors:
                    elements = post_element.find_elements(By.XPATH, selector)
                    if elements and len(elements) > 0:
                        has_video = True
                        break

            except Exception:
                pass

            # Medya içeren gönderilere bonus puan
            media_bonus = 10 if has_image else 0
            media_bonus += 15 if has_video else 0

            # Etkileşim yoğunluğu bonusu
            engagement_ratio = min(
                100, (comment_count + retweet_count + like_count) / max(1, view_count) * 1000)
            engagement_bonus = min(50, engagement_ratio)

            # Etkileşim çeşitliliği bonusu
            diversity_bonus = 0
            if comment_count >= 5:
                diversity_bonus += 5
            if retweet_count >= 5:
                diversity_bonus += 5
            if like_count >= 10:
                diversity_bonus += 5

            # Temel skor hesaplama - ağırlıklı
            base_score = (comment_count * 5) + (retweet_count *
                                                3) + (like_count * 1) + (view_count * 0.01)

            # Toplam skor
            total_score = base_score + media_bonus + engagement_bonus + diversity_bonus + betting_content_bonus

            # Minimum bir skor garantile
            total_score = max(5, total_score)

            logger.debug(
                f"[{self.account.username}] Skor detayları: Temel={base_score:.1f}, Medya={media_bonus}, "
                f"Etkileşim={engagement_bonus:.1f}, Çeşitlilik={diversity_bonus}, Bahis İçerik={betting_content_bonus}")

            return total_score

        except Exception as e:
            logger.warning(
                f"[{self.account.username}] Skor hesaplama hatası: {str(e)}")
            return 5  # Hata durumunda varsayılan skor

    def collect_and_analyze_tweets(self, max_tweets=30, min_likes=10):
        """
        Tweet'leri toplar ve analiz eder, sonuçları dosyaya kaydeder

        :param max_tweets: Toplanacak maksimum tweet sayısı
        :param min_likes: Analiz için minimum beğeni sayısı
        :return: Analiz başarılı mı
        """
        try:
            logger.info(f"[{self.account.username}] Tweet analizi başlatılıyor")

            # Analiz sonuçları için dizin oluştur
            analysis_dir = Path("tweet_analyses")
            analysis_dir.mkdir(exist_ok=True)

            # Tarih bazlı dosya adı
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            analysis_file = analysis_dir / f"{self.account.username}_analysis_{timestamp}.json"

            # Analiz için liste
            all_analyzed_posts = []

            # Maksimum 3 kez tekrar et
            for iteration in range(3):
                # Ana sayfaya git
                self.driver.get("https://x.com/home?mx=2")
                time.sleep(5)

                # 7'ye kadar olan tüm tweet kartlarını analiz et
                for tweet_index in range(1, 8):
                    tweet_xpath = f"(//article[contains(@class,'css-175oi2r r-18u37iz')])[{tweet_index}]"
                    
                    try:
                        # Tweet kartını bul
                        tweet_element = self.wait.until(
                            EC.presence_of_element_located((By.XPATH, tweet_xpath))
                        )

                        # Tweet içeriğini al
                        try:
                            tweet_text, has_image, image_description = self.get_tweet_content(tweet_element)
                            
                            # Etkileşim skorunu hesapla
                            score = self.calculate_post_score(tweet_element)
                            
                            # Minimum beğeni sayısını kontrol et
                            if score > min_likes:
                                analyzed_post_data = {
                                    'iteration': iteration + 1,
                                    'tweet_index': tweet_index,
                                    'text': tweet_text,
                                    'has_image': has_image,
                                    'image_description': image_description,
                                    'score': score,
                                    'comment_count': self.get_interaction_count(tweet_element, 1),
                                    'retweet_count': self.get_interaction_count(tweet_element, 2),
                                    'like_count': self.get_interaction_count(tweet_element, 3),
                                    'view_count': self.get_interaction_count(tweet_element, 4),
                                    'contains_betting_content': self.check_betting_content(tweet_text)
                                }
                                
                                all_analyzed_posts.append(analyzed_post_data)
                                
                                logger.info(f"[{self.account.username}] Tweet analiz edildi (İterasyon {iteration + 1}, Tweet {tweet_index}): Skor={score:.1f}, Metin: {tweet_text[:50]}...")

                        except Exception as e:
                            logger.warning(f"[{self.account.username}] Tweet içeriği çekme hatası (Tweet {tweet_index}): {e}")

                    except Exception as e:
                        logger.error(f"[{self.account.username}] Tweet seçme hatası (Tweet {tweet_index}): {e}")

                # Her iterasyon sonunda biraz bekle
                time.sleep(3)
                
                # Sayfayı kaydır ve daha fazla tweet yükle
                self.driver.execute_script("window.scrollBy(0, 1000);")
                time.sleep(3)

            # Gemini AI ile tweet analizi
            ai_analysis = self.perform_ai_tweet_analysis(all_analyzed_posts)

            # Analiz sonuçlarını kaydet
            self.analysis_results = {
                'total_posts_analyzed': len(all_analyzed_posts),
                'tweet_suggestions': self.generate_casino_tweet_suggestions(all_analyzed_posts, ai_analysis),
                'ai_insights': ai_analysis
            }

            # JSON dosyasına kaydet
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': timestamp,
                    'analyzed_posts': all_analyzed_posts,
                    'suggestions': self.analysis_results['tweet_suggestions'],
                    'insights': ai_analysis
                }, f, ensure_ascii=False, indent=4)

            # Tüm veriyi sınıf değişkenine de kaydet
            self.tweets_data.extend(all_analyzed_posts)
            # Veri büyürse en fazla son 500 veriyi tut
            if len(self.tweets_data) > 500:
                self.tweets_data = self.tweets_data[-500:]

            logger.info(f"[{self.account.username}] Toplam {len(all_analyzed_posts)} tweet analiz edildi ve {analysis_file} dosyasına kaydedildi")
            return True

        except Exception as e:
            logger.error(f"[{self.account.username}] Tweet analizi hatası: {e}")
            return False
            
    def check_betting_content(self, text):
        """
        Tweet metninde bahis/casino içeriği olup olmadığını kontrol eder
        
        :param text: Tweet metni
        :return: Bahis içeriği var mı
        """
        if not text:
            return False
            
        betting_keywords = [
            'bahis', 'casino', 'slot', 'bonus', 'jackpot', 'rulet', 'blackjack', 'poker',
            'free spin', 'bet', 'odds', 'oranlar', 'maç', 'kupon', 'iddaa', 
            'kazanç', 'para', 'kazandır', 'fırsat', 'promosyon', 'spor bahis',
            'canlı bahis', 'kombine', 'para yatırma', 'çekim', 'free bet', 'çevrimsiz'
        ]
        
        text_lower = text.lower()
        for keyword in betting_keywords:
            if keyword in text_lower:
                return True
                
        return False
        
    def perform_ai_tweet_analysis(self, analyzed_posts):
        """
        Gemini AI kullanarak tweet analizini gerçekleştirir
        
        :param analyzed_posts: Analiz edilmiş tweetler
        :return: AI tarafından oluşturulan görüşler
        """
        try:
            if not self.gemini_model:
                return {"error": "Gemini AI modeli başlatılmamış"}
                
            if not analyzed_posts or len(analyzed_posts) < 3:
                return {"error": "Yeterli analiz edilmiş tweet yok"}
                
            # En yüksek skorlu tweetleri seç
            top_posts = sorted(analyzed_posts, key=lambda x: x['score'], reverse=True)[:10]
            
            # En düşük skorlu tweetleri seç
            bottom_posts = sorted(analyzed_posts, key=lambda x: x['score'])[:5]
            
            # Analiz promptu oluştur
            analysis_prompt = f"""
            Bahis ve casino Twitter pazarlaması için tweet analizi yap.
            
            En Yüksek Skorlu Tweetler:
            {json.dumps(top_posts, ensure_ascii=False, indent=2)}
            
            En Düşük Skorlu Tweetler:
            {json.dumps(bottom_posts, ensure_ascii=False, indent=2)}
            
            Şu analizleri gerçekleştir:
            1. En etkili tweet formatı ve özellikleri
            2. En sık kullanılan ve etkili hashtag'ler
            3. Görsel kullanımının etkisi
            4. Yüksek etkileşim saatleri
            5. Başarılı bahis/casino/spor/ pazarlama dili özellikleri
            6. Bir sonraki tweet kampanyası için tavsiyeler
            
            JSON formatında yanıt ver:
            {{
                "effective_format": "En etkili tweet formatı analizi",
                "effective_hashtags": ["en", "etkili", "hashtagler"],
                "visual_impact": "Görsellerin etkileşime etkisi",
                "optimal_posting_times": ["en", "iyi", "paylaşım", "zamanları"],
                "effective_language": "Etkili bahis pazarlama dili özellikleri",
                "next_campaign_recommendations": ["tavsiye1", "tavsiye2", "tavsiye3"]
            }}
            """
            
            # Gemini'den yanıt al
            response = self.gemini_model.generate_content(analysis_prompt)
            
            try:
                # Yanıtı JSON olarak ayrıştır
                analysis = json.loads(response.text)
                return analysis
            except json.JSONDecodeError:
                # JSON ayrıştırma hatası durumunda düz metin olarak döndür
                return {"analysis_text": response.text}
                
        except Exception as e:
            logger.error(f"[{self.account.username}] AI tweet analizi hatası: {e}")
            return {"error": str(e)}
        
    def analyze_content_category(self, tweet_text, image_description=None):
        """
        Tweet içeriğinin hangi kategoriye ait olduğunu Gemini AI ile analiz eder
        
        :param tweet_text: Tweet metni
        :param image_description: Görsel açıklaması (varsa)
        :return: İçerik kategorisi (sports, betting, casino, other)
        """
        try:
            # Gemini modeli mevcut değilse, basit metin analizi yap
            if not self.gemini_model:
                # Basit bir metin kontrolü
                text_lower = tweet_text.lower()
                
                if any(word in text_lower for word in ['maç', 'futbol', 'gol', 'lig', 'transfer']):
                    return 'sports'
                    
                if any(word in text_lower for word in ['bahis', 'oran', 'kupon', 'iddaa', 'tahmin']):
                    return 'betting'
                    
                if any(word in text_lower for word in ['casino', 'slot', 'bonus', 'jackpot', 'rulet']):
                    return 'casino'
                    
                return 'other'
            
            # Gemini AI kullanarak daha sofistike analiz yap
            img_info = f"İçerdiği görsel açıklaması: {image_description}" if image_description else "Görselsiz tweet."
            
            prompt = f"""
            Aşağıdaki tweet içeriğini analiz et ve en uygun kategoriyi belirle:
            
            Tweet metni: "{tweet_text}"
            
            {img_info}
            
            Kategoriler:
            - sports: Futbol, basketbol, diğer sporlar, maçlar, sporcular, ligler, turnuvalar
            - betting: Bahis, iddaa, oranlar, kuponlar, tahminler, bahis tavsiyeleri
            - casino: Casino oyunları, slot, jackpot, poker, rulet, bahis platformları
            - other: Diğer tüm konular
            
            Sadece tek bir kategori adını döndür (sports, betting, casino veya other).
            """
            
            response = self.gemini_model.generate_content(prompt)
            category = response.text.strip().lower()
            
            # Sadece geçerli kategorileri kabul et
            valid_categories = ['sports', 'betting', 'casino', 'other']
            if category not in valid_categories:
                # Tam eşleşme yoksa, içeriğe bakarak en yakın kategoriyi seç
                for valid_cat in valid_categories:
                    if valid_cat in category:
                        return valid_cat
                return 'other'
                
            return category
            
        except Exception as e:
            logger.error(f"[{self.account.username}] İçerik kategori analizi hatası: {e}")
            return 'other'  # Hata durumunda varsayılan kategori
            
    def generate_casino_tweet_suggestions(self, analyzed_posts, ai_analysis):
        """
        Analiz edilen tweetlerden yeni casino/bahis tweet önerileri oluşturur
        
        :param analyzed_posts: Analiz edilmiş tweetler
        :param ai_analysis: Gemini AI'dan gelen analiz
        :return: Tweet önerileri listesi
        """
        try:
            suggestions = []
            
            # Gemini AI'dan tweet önerileri üret
            if self.gemini_model:
                # Etkili hashtagleri analiz sonuçlarından al
                effective_hashtags = []
                if ai_analysis and "effective_hashtags" in ai_analysis:
                    effective_hashtags = ai_analysis["effective_hashtags"]
                
                # Optimal paylaşım zamanlarını al
                optimal_times = []
                if ai_analysis and "optimal_posting_times" in ai_analysis:
                    optimal_times = ai_analysis["optimal_posting_times"]
                
                # Başarılı tweet örneklerini topla
                successful_examples = []
                if analyzed_posts:
                    # En yüksek skorlu 5 tweeti al
                    top_posts = sorted(analyzed_posts, key=lambda x: x['score'], reverse=True)[:5]
                    successful_examples = [post['text'] for post in top_posts if 'text' in post]
                
                suggestion_prompt = f"""
Hedef: Kullanıcıların **hemen kayıt olması** ve içeriklere **yoğun etkileşim** göstermesi (beğeni, yorum, retweet).

Bu hedeflere ulaşmak için **ileri düzey psikolojik manipülasyon teknikleri** ve **satış stratejileri** kullanarak, **5 adet profesyonel**, **yüksek dönüşüm oranına sahip**, **hipnotize edici** bahis/casino temalı tweet oluştur.

Başarılı Tweet Örnekleri:
{json.dumps(successful_examples, ensure_ascii=False)}

Etkili Hashtagler:
{json.dumps(effective_hashtags, ensure_ascii=False)}

Optimal Paylaşım Zamanları:
{json.dumps(optimal_times, ensure_ascii=False)}

Tweetlerde Bulunması Gereken Özellikler:


1. **En fazla 180 karakter**.
2. İlk cümlede **sert bir dikkat çekici giriş** kullanılmalı ("Şok", "Son Şans", "Müthiş Kazanç Fırsatı!" gibi).
3. **Kıtlık ve aciliyet duygusu** güçlü şekilde işlenmeli ("Sınırlı süre", "Son 300 kişi" gibi).
4. **Topluluk etkisi** oluşturulmalı ("6.000'den fazla kişi katıldı!").
5. **Fırsatı kaçıranların kaybedeceği** özellikle vurgulanmalı.
6. **Güçlü ve doğrudan CTA** eklenmeli ("Çevrimsiz 500 Deneme bonusunu kap!","Çevrimsiz 500 FreeSpin'i heme kap!", "Şansını hemen kullan").
7. 1-2 **hedefli emoji** kullanılabilir (mantıklı yerlerde).
15. **Site bağlantısı olarak yalnızca** **"https://cutt.ly/mrlOjHcY"** kullanılacak.
8. **Şartsız Bonuslar**, **Çevrimsiz Freespinler**, **%25 cashback fırsatları** çok net ifade edilmeli.
9. **Üye Olanların kazanabileceği** fırsatlar belirtilecek.
11. **Yorum, beğeni ve RT yapanlara ekstra ödül** sunulmalı.
12. **Hayal tetikleyici** ifadeler eklenmeli ("Hayalini yaşa", "Büyük kazanç için 1 adım uzağındasın").
13. Tweetler **özgün**, **tekrarsız** ve **çok profesyonel** yazılmalı.
14. İçerikte **en ufak bir olumsuz veya şüpheli algı** olmamalı.
16. **Deneme Bonusu 500 adet ve Freespin 500 adet olcak şekilde paylaşımlar yapılacak.**

Manipülasyon Teknikleri:
- **Kıtlık** ("Sınırlı kişi, sınırlı süre").
- **Kaybetme korkusu** ("Şimdi katılmazsan büyük fırsatı kaçırırsın!").
- **Topluluk baskısı** ("Binlerce kişi kazandı, sen hâlâ bekliyor musun?").
- **Somut ve çekici ödüller** ("500 Deneme Bonusu + 500 Freespin!").
- **Katılmayanın kaybı abartılacak**.

Örnek Profesyonel ve Manipülatif Tweetler:
1. "🎰 Sadece Kayıt olanlara: Şartsız 500 Deneme Bonusu + 500 freespin!

🎁 Şans kapını çalıyor, kaçıran kaybeder!

⏳ Şimdi yatırım yap: https://cutt.ly/mrlOjHcY"

2. "⚡ SON ŞANS! Kayıt Olana Deneme bonusu!

🎯 10.000+ kişi kazandı, sıra sende!

Katıl: https://cutt.ly/mrlOjHcY"

3. "🔥 Şu an 7.000+ kişi kazandı! Sen neden dışarıdasın?

Deneme Bonusu seni bekliyor!

Hemen katıl: https://cutt.ly/mrlOjHcY"

4. "💎 VIP Çekiliş Başladı!

Kayıt Olanlara özel ödüller kazanıyor.

🎉 Şimdi yorum yap, beğen, RT at, bonusu kap: https://cutt.ly/mrlOjHcY"

Çıktı Şartı:
- **Sadece 5 adet tweet** üret.
- Her biri **özgün**, **hipnotize edici**, **Kayıt odaklı** olsun.
- **Her tweet ayrı bir paragraf olacak.**
- **Her paragraf arasında 2 adet boşluk olacak.**
- **Açıklama, yorum veya başka metin ekleme**. Sadece saf tweet çıktısı ver.
- **link ekleneceği zaman yalnızca "https://cutt.ly/mrlOjHcY" eklenicek. başka hiç bir link eklenmeyecek!**
"""
                
                # Gemini'den yanıt al
                response = self.gemini_model.generate_content(suggestion_prompt)
                
                # Yanıtı işle ve önerileri ayıkla
                suggestion_lines = response.text.strip().split('\n')
                raw_suggestions = [line.strip() for line in suggestion_lines if line.strip() and not line.startswith('#')]
                
                # Tweet sınırlamaları kontrol et ve temizle
                for suggestion in raw_suggestions:
                    # Kısa yan metinleri kaldır
                    if len(suggestion) < 20:
                        continue
                        
                    # Karakter kontrolü
                    if len(suggestion) > 280:
                        suggestion = suggestion[:277] + "..."
                        
                    # # Sorumlu bahis etiketinin varlığını kontrol et, yoksa ekle
                    # if "@1kingbet" not in suggestion and "@1kingbet" not in suggestion and "#sorumlu" not in suggestion:
                    #     suggestion += " @1kingbet"
                        
                    # # 18+ kontrolü
                    # if "18+" not in suggestion:
                    #     suggestion += " 18+"
                        
                    # Önerilere ekle
                    suggestions.append(suggestion)
            
            # Yeterli öneri yoksa varsayılan önerileri ekle
            if len(suggestions) < 3:
                default_suggestions = [
                    "🔥 Büyük Jackpot Fırsatı! Bu hafta 500.000TL değerinde ödül havuzu sizi bekliyor. Hemen katıl, şansını dene! #Casino #Jackpot @alobetgiris 18+",
                    "⚽ Bugünün maçları için özel oranlar yayında! İlk Kaydınızda 750 Deneme bonusu. Kaçırmayın! #Bahis #YüksekOran @alobetgiris 18+",
                    "🎲 Hafta sonu özel: 100 Free Spin + %50 yatırım bonusu! Sadece bu akşam için geçerli. Hemen üye ol, kazanmaya başla! #Slot #Bonus @alobetgiris 18+"
                ]
                
                # Eksik önerileri tamamla
                for i in range(min(3, 3 - len(suggestions))):
                    if i < len(default_suggestions):
                        suggestions.append(default_suggestions[i])
            
            return suggestions[:5]  # En fazla 5 öneri döndür
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Casino tweet önerisi oluşturma hatası: {e}")
            # Hata durumunda varsayılan öneriler
            return [
                "🎰 Yeni slot oyunlarımızı denediniz mi? İlk yatırımınıza %100 bonus! #Casino #Slot @alobetgiris 18+",
                "⚽ Büyük derbiler, büyük heyecan! Canlı bahis seçenekleriyle kazanan sen ol! #Bahis #MacKazandiran @alobetgiris 18+",
                "💰 Hafta sonu fırsatı: 50TL yatır, 150TL ile oyna! Teklif sadece 24 saat geçerli! #Bonus #Firsat @alobetgiris 18+"
            ]
            
            
    def generate_contextual_comment(self, tweet_text, profile_handle, has_image=False, image_description="", existing_comments=None):
        """
        İçerik kategorisine göre özelleştirilmiş bağlamsal yorum oluşturur
        
        :param tweet_text: Tweet metni
        :param profile_handle: Profil kullanıcı adı
        :param has_image: Görselli tweet mi
        :param image_description: Görsel açıklaması
        :param existing_comments: Mevcut yorumlar (opsiyonel)
        :return: Oluşturulan yorum
        """
        try:
            # Gemini modeli mevcut mu kontrol et
            if not self.gemini_model:
                # Basit yedek yorum
                return f"Çok güzel bir paylaşım! @{profile_handle}"
            
            # Görsel bilgisi
            img_info = f"\nGörselin içeriği: {image_description}" if has_image and image_description else ""
            
            # Kategori bazlı bilgiler ve örnekler
            category_info = {
                'sports': "Bu tweet spor/futbol içeriğine sahip.",
                'betting': "Bu tweet bahis/tahmin içeriğine sahip.",
                'casino': "Bu tweet casino/şans oyunları içeriğine sahip.",
                'other': "Bu tweet genel bir içeriğe sahip."
            }
            
            category_examples = {
                'sports': [
                    f"Bu maç analizi çok yerinde, ben de aynı fikirdeydim! @{profile_handle}",
                    f"Son dönemdeki performansı gerçekten etkileyici. @{profile_handle}"
                ],
                'betting': [
                    f"Bu oranlar gerçekten cazip görünüyor. Teşekkürler. @{profile_handle}",
                    f"Tahminlerin genelde tutuyor, bu da mantıklı duruyor. @{profile_handle}"
                ],
                'casino': [
                    f"Bu bonus fırsatını kaçırmamak lazım, teşekkürler. @{profile_handle}",
                    f"Jackpot stratejin ilginç, deneyeceğim. @{profile_handle}"
                ],
                'other': [
                    f"Haklısın, kesinlikle katılıyorum bu görüşe. @{profile_handle}",
                    f"İlginç bir bakış açısı, düşünmeye değer. @{profile_handle}"
                ]
            }
            
            # Varsayılan kategori (category parametresi eksik olduğu için 'other' kullanıldı)
            category = 'other'
            
            # Prompt oluşturma
            prompt = f"""
    Tweet içeriği: "{tweet_text}"
    {img_info}

    Bilgi: {category_info.get(category, category_info['other'])}

    Görev: Bu tweet'e doğal, kısa ve ilgili bir yorum yaz. Yorumun tweet konusuyla alakalı ve gerçekçi olsun.

    Yanıtın şu özelliklere sahip olmalı:
    1. 100-150 karakter arasında kısa ve öz
    2. Tweet içeriğine uygun bağlamda
    3. Doğal ve samimi bir ton
    4. Tweet özel bir promosyon/bonus/oran içeriyorsa, ona özel ilgi göstermeli
    5. Gerekirse sempatik şekilde argo kelimeler kullan
    6. Sempatik şekilde tartışma yaratsın
    7. İnsan gibi yorumlar yapsın
    8. Çok fazla dikkat çekecek yorumlar yap

    Örnekler:
    {category_examples.get(category, category_examples['other'])[0]}
    {category_examples.get(category, category_examples['other'])[1]}

    Sadece yanıtı döndür, başka açıklama yapma.
    """
            
            # Gemini AI'dan yanıt alma
            response = self.gemini_model.generate_content(prompt)
            comment_text = response.text.strip().replace('"', '').replace("'", "")
            
            # @ işareti kontrolü
            if f"@{profile_handle}" not in comment_text:
                comment_text += f" @{profile_handle}"
            
            # Karakter limiti kontrolü
            if len(comment_text) > 240:
                comment_text = comment_text[:230] + f" @{profile_handle}"
            
            logger.info(f"[{self.account.username}] Oluşturulan {category} yorumu: {comment_text}")
            return comment_text
        
        except Exception as e:
            logger.error(f"[{self.account.username}] Yorum oluşturma hatası: {e}")
            return f"Çok güzel bir paylaşım! @{profile_handle}"
    
    
    
        
    
    def generate_betting_contextual_comment(self, tweet_text, profile_handle, matched_keywords=None, 
                                       promo_contexts=None, has_image=False, image_description=""):
        """
        Gemini AI kullanarak bahis/casino tweet'ine bağlamsal ve daha insansı yorumlar oluşturur.
        
        :param tweet_text: Hedef tweetin metni
        :param profile_handle: Yönlendirilecek profil adı (@ işareti olmadan)
        :param matched_keywords: Eşleşen bahis/casino anahtar kelimeleri
        :param promo_contexts: Promosyon bağlamları (bonus, yatırım vb)
        :param has_image: Tweet'te görsel var mı
        :param image_description: Görsel ile ilgili açıklama metni
        :return: Oluşturulan yorum metni
        """
        try:
            # Gemini modeli kontrolü
            if not self.gemini_model:
                return f"Harika bir bahis fırsatı! İlgilenenlere tavsiye ederim @{profile_handle}"

            # Metin kontrolü
            if not tweet_text or len(tweet_text.strip()) < 5:
                tweet_text = "Bu bahis fırsatı gerçekten dikkat çekici!"
                
            # Varsayılan değerler
            if not matched_keywords:
                matched_keywords = ["bahis", "bonus"]
                
            if not promo_contexts:
                promo_contexts = ["bonus", "yatırım", "özel"]

            # Geliştirilmiş prompt - bahis ve casino bağlamına uygun
            prompt = f"""
            Tweet içeriği: "{tweet_text}"
            
            {f"Tweet'teki görsel: {image_description}" if has_image else "Tweet'te görsel yok."}
            
            Eşleşen Bahis/Casino Anahtar Kelimeleri: {', '.join(matched_keywords)}
            
            Görev: Bu bahis/casino tweet'ine yanıt olarak tamamen doğal, insansı, ikna edici ve yaratıcı bir yorum oluştur.
            
            Yanıtın şu özelliklere sahip olmalı:
            1. Bahis/casino promosyonuna ilgi gösteren, gerçek bir bahisçinin yazacağı gibi doğal ve akıcı olmalı
            2. İlgi çekici ve meraklı bir ton kullanmalı (örn: "Bu oranlar gerçekten iyi mi?", "Bu bonusu deneyenler var mı?")
            3. Yaratıcı ve özgün olmalı - klişelerden kaçınmalı
            4. Tweet'in bahis içeriğine spesifik referanslar yapmalı
            5. Sadece ASCII karakterleri ve Türkçe karakterler kullanmalı - emoji içermemeli
            6. Üç nokta yerine "..." kullanmalı, özel Unicode karakterler kullanmamalı
            7. Günlük bahis konuşma dilini tercih etmeli 
            8. Kısa ve etkili olmalı (30-100 karakter arası)
            10. Tweet özel bir promosyon/bonus/oran içeriyorsa, ona özel ilgi göstermeli
            11. Gerekirse sempatik şekilde argo kelimeler kullan
            12. Sempatik şekilde tartışma yaratsın.
            13. İnsan gibi yorumlar yapsın
            14. Çok fazla dikkat çekicek yorumlar yap
            
            Yorumu, bahisçi olarak diğer bahisçilerle konuşuyormuş gibi oluştur. Gerçek bir bahisçinin bahis fırsatlarına nasıl yanıt vereceğini düşün.
            
            KESINLIKLE EMOJI KULLANMA ve SADECE STANDART ASCII KARAKTERLERINI ve TÜRKÇE HARFLERİ KULLAN.
            ÖZEL KARAKTERLER VEYA UNICODE SEMBOLLER KULLANMA.

            Sadece yanıtı döndür, başka açıklama ekleme. Tırnak işaretleri kullanma.
            """

            # Gemini API'dan yanıt alma
            response = self.gemini_model.generate_content(prompt)
            comment_text = response.text.strip().replace('"', '').replace("'", "")

            # Özel karakterleri temizleme
            import re
            # Sadece ASCII karakterleri ve Türkçe harfleri tut
            comment_text = re.sub(
                r'[^\x00-\x7F\u00C0-\u00FF\u0100-\u017F\u0180-\u024F\u0370-\u03FF\u0400-\u04FF]', '', comment_text)

            # @ işareti kontrolü
            if f"@{profile_handle}" not in comment_text:
                # Yorumun sonuna ekle
                comment_text += f" @{profile_handle}"

            # Karakter limiti kontrolü (Twitter 280 karakter)
            if len(comment_text) > 240:
                comment_text = comment_text[:237] + "..."

            # Son bir kontrol - ASCII olmayan karakterleri temizle
            comment_text = ''.join(c for c in comment_text if ord(
                c) < 128 or (ord(c) >= 192 and ord(c) <= 687))

            return comment_text

        except Exception as e:
            logger.error(
                f"[{self.account.username}] Bahis yorum oluşturma hatası: {e}")
            # Hata durumunda yedek yorum döndür
            return f"Bu bahis fırsatı gerçekten ilginç! Detaylara bakacağım @{profile_handle}"
        
    # Önceki hata: 'TwitterBot' object has no attribute 'generate_contextual_comment_with_existing'
# İki fonksiyonu birleştirip tek bir düzeltme olarak sunalım

# Ana fonksiyon: Bağlamsal yorumlar için
    @smart_retry
    def perform_community_interactions(self) -> bool:
        """
        Twitter'da ana sayfadaki en yüksek etkileşimli gönderiye bağlamsal yorum yapar
        ve yoruma görsel ekler.
        
        :return: İşlem başarılı mı
        """
         # Görsel ekleme seçeneğini tanımla
        include_image = True  # Görselsiz yorum yapmak için False, görselli için True
    
        try:
            logger.info(f"[{self.account.username}] Bağlamsal yorum işlemi başlatılıyor...")

            # Ana sayfaya git
            self.driver.get("https://x.com/home?mx=2")
            time.sleep(5)

            # Postları bul - ilk 20 post
            posts = self.find_all_posts()[:20]

            if not posts:
                logger.warning(f"[{self.account.username}] Hiç post bulunamadı")
                return False

            # Postları analiz et ve puanla
            analyzed_posts = []
            
            for idx, post in enumerate(posts):
                try:
                    # Tweet içeriğini al
                    tweet_text, has_image, image_description = self.get_tweet_content(post)
                    
                    if not tweet_text:
                        continue
                    
                    # Tweet URL'sini al
                    tweet_url = self.get_tweet_url(post)
                    
                    # Kullanıcı adını al
                    try:
                        username_element = post.find_element(By.XPATH, ".//div[contains(@data-testid, 'User-Name')]//a")
                        profile_handle = username_element.get_attribute('href').split('/')[-1]
                    except:
                        profile_handle = "user"
                    
                    # Etkileşim sayılarını al
                    comment_count = self.get_interaction_count(post, 1)
                    retweet_count = self.get_interaction_count(post, 2)
                    like_count = self.get_interaction_count(post, 3)
                    view_count = self.get_interaction_count(post, 4)
                    
                    # Puanı hesapla
                    score = (comment_count * 5) + (retweet_count * 3) + (like_count * 1)
                    
                    # Post bilgilerini sakla
                    analyzed_posts.append({
                        'index': idx,
                        'element': post,
                        'text': tweet_text,
                        'has_image': has_image,
                        'image_description': image_description,
                        'score': score,
                        'url': tweet_url,
                        'profile_handle': profile_handle,
                        'comment_count': comment_count,
                        'retweet_count': retweet_count,
                        'like_count': like_count,
                        'view_count': view_count
                    })
                    
                    logger.info(f"[{self.account.username}] Tweet #{idx} analiz edildi - Puan: {score}, Metin: {tweet_text[:50]}...")
                    
                except Exception as e:
                    logger.warning(f"[{self.account.username}] Tweet #{idx} analiz hatası: {e}")
                    continue
            
            # Hiç post analiz edilmediyse işlemi sonlandır
            if not analyzed_posts:
                logger.warning(f"[{self.account.username}] Hiç tweet analiz edilemedi")
                return False
            
            # Puanı en yüksek olan tweet'i seç
            best_post = max(analyzed_posts, key=lambda x: x['score'])
            
            logger.info(
                f"[{self.account.username}] En yüksek puanlı tweet seçildi - #{best_post['index']}, "
                f"Puan: {best_post['score']}, "
                f"İstatistikler: Yorum: {best_post['comment_count']}, RT: {best_post['retweet_count']}, Beğeni: {best_post['like_count']}, "
                f"Metin: {best_post['text'][:50]}..."
            )
            
            # Tweete tıkla ve sayfasına git
            try:
                post_element = best_post['element']
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", post_element)
                time.sleep(1)
                
                # Tweet'e tıkla
                self.driver.execute_script("arguments[0].click();", post_element)
                logger.info(f"[{self.account.username}] Seçilen tweet'e tıklandı")
                time.sleep(5)
                
                # Önceki yorumları topla
                existing_comments = []
                max_comments_to_read = 15
                
                for i in range(1, max_comments_to_read + 1):
                    try:
                        comment_xpath = f"(//div[contains(@class,'css-901oao css-16my406 r-poiln3')])[{i}]"
                        comment_element = self.driver.find_element(By.XPATH, comment_xpath)
                        comment_text = comment_element.text
                        
                        if comment_text and len(comment_text.strip()) > 0:
                            existing_comments.append(comment_text)
                    except Exception:
                        break
                
                # Bağlamsal yorum oluştur
                comment_text = self.generate_contextual_comment(
                    best_post['text'], 
                    best_post['profile_handle'],
                    best_post['has_image'],
                    best_post['image_description'],
                    existing_comments
                )
                
                # Yorum butonuna tıkla
                try:
                    comment_button = self.wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "(//div[@class='css-175oi2r r-xoduu5']//div)[3]")
                    ))
                    self.driver.execute_script("arguments[0].click();", comment_button)
                    time.sleep(2)
                except Exception as e:
                    logger.warning(f"[{self.account.username}] Yorum butonu bulunamadı: {e}")
                    # Alternatif yorum butonları deneyebilirsiniz
                    try:
                        alt_buttons = self.driver.find_elements(By.XPATH, "//div[@role='button']")
                        if alt_buttons and len(alt_buttons) > 0:
                            self.driver.execute_script("arguments[0].click();", alt_buttons[0])
                    except Exception:
                        pass
                
                # Yorum kutusuna yazı yaz
                comment_box = self.wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//div[@data-testid='tweetTextarea_0']")
                ))
                comment_box.clear()
                
                # Metni insan gibi daha doğal gir
                for char in comment_text:
                    comment_box.send_keys(char)
                    time.sleep(random.uniform(0.01, 0.03))
                    
                logger.info(f"[{self.account.username}] Yorum metni yazıldı")
                time.sleep(2)
                
                
                # # Görsel yükleme -BURASI
                # if include_image:
                #     try:
                #         element = WebDriverWait(self.driver, 15).until(
                #             EC.element_to_be_clickable(
                #                 (By.XPATH, "//div[contains(@class,'css-175oi2r r-1pi2tsx')]//button"))
                #         )
                #         self.driver.execute_script(
                #             "arguments[0].click();", element)
                #         time.sleep(2)

                #         # Görsel girişi
                #         image_input = self.driver.find_element(
                #             By.XPATH, "//input[@data-testid='fileInput']")
                #         image_path = self.get_random_image(exclude_used=True)
                #         if image_path:
                #             image_input.send_keys(image_path)
                #             time.sleep(10)  # Görsel yüklenmesi için bekle
                #             logger.info(
                #                 f"[{self.account.username}] Görselli tweet paylaşılıyor")
                #         else:
                #             include_image = False
                #             logger.warning(f"[{self.account.username}] Görsel bulunamadı, görselsiz devam ediliyor")
                #     except Exception as e:
                #         logger.warning(
                #             f"[{self.account.username}] Görsel yükleme hatası: {e}")
                #         include_image = False
                
                # Paylaş butonuna tıkla
                try:
                    submit_button = self.wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//div[contains(@class,'css-175oi2r r-1vsu8ta')]/following-sibling::button[1]")
                    ))
                    self.driver.execute_script("arguments[0].click();", submit_button)
                except Exception as e:
                    logger.warning(f"[{self.account.username}] İlk paylaş butonu hatası: {e}")
                    
                    # Alternatif paylaş butonları
                    try:
                        alt_buttons = [
                            "//div[contains(@data-testid,'tweetButton')]",
                            "//span[contains(text(),'Reply')]/ancestor::div[@role='button']",
                            "//div[contains(@class,'css-175oi2r r-sdzlij')]//div[@role='button']"
                        ]
                        
                        for xpath in alt_buttons:
                            try:
                                button = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                                self.driver.execute_script("arguments[0].click();", button)
                                logger.info(f"[{self.account.username}] Alternatif paylaş butonuna tıklandı")
                                break
                            except Exception:
                                continue
                    except Exception as e2:
                        logger.error(f"[{self.account.username}] Alternatif paylaş butonu da bulunamadı: {e2}")
                        return False
                
                # Başarı kontrolü
                time.sleep(5)
                logger.info(f"[{self.account.username}] Görselli bağlamsal yorum paylaşıldı: {comment_text}")
                return True
                
            except Exception as e:
                logger.error(f"[{self.account.username}] Yorum paylaşma hatası: {e}")
                return False
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Bağlamsal yorum işlemi genel hatası: {e}")
            return False



    def generate_contextual_comment(self, tweet_text, profile_handle, has_image=False, 
                                image_description="", existing_comments=None):
        """
        Doğal, insan gibi görünen ve kendisini etiketleyen bağlamsal yorumlar oluşturur
        
        :param tweet_text: Tweet metni
        :param profile_handle: Profil kullanıcı adı (kullanılmayacak)
        :param has_image: Görselli tweet mi
        :param image_description: Görsel açıklaması
        :param existing_comments: Mevcut yorumlar listesi
        :return: Oluşturulan bağlamsal yorum
        """
        try:
            # Mevcut yorumlar yoksa veya boşsa
            if not existing_comments:
                existing_comments = []
            
            # Kendi kullanıcı adını al
            own_username = self.account.username.replace("@", "")
            
            # Gemini AI kullanılabilir mi kontrol et
            if not self.gemini_model:
                return f"Harbiden saçmalamışsın ya! Gülmekten öldüm ben buna @{own_username}"
            
            # Metin kontrolü
            if not tweet_text or len(tweet_text.strip()) < 5:
                tweet_text = "Bu paylaşım gerçekten ilgi çekici görünüyor!"

            # Eğer çok fazla yorum varsa, en etkileyici birkaç tanesini seç
            selected_comments = existing_comments[:3] if len(existing_comments) > 3 else existing_comments
            
            # Yorumları metin haline getir
            comments_text = "\n".join([f"- {comment}" for comment in selected_comments])
            
            # Bağlamsal yorum için gelişmiş prompt
            prompt = f"""
            Tweet içeriği: "{tweet_text}"
            {f"Tweet'teki görsel: {image_description}" if has_image else "Tweet'te görsel yok."}
            {f"Tweet'e yapılmış mevcut yorumlar ({len(existing_comments)} yorum):" if existing_comments else "Bu tweet'e henüz yorum yapılmamış."}
            {comments_text if existing_comments else ""}

            Görev: Bu tweet için tamamen doğal görünen, espirili ve insan gibi bir yorum oluştur ve birazda tartışma yaratıcak yorumlar yap.

            Örnek olarak, kendi Twitter hesabımda (@{own_username}) önce normal bir bahis/spor yorumu yapmalıyım

            Yorumun özellikleri:
            1. KESİNLİKLE BOT GİBİ GÖRÜNMEMELİ. Yapmacık olmamalı.
            2. Önce futbol/spor/bahisle ilgili doğal bir yorum/görüş belirt
            4. Hafif argo veya futbol taraftarı jargonu içerebilir, ama aşırıya kaçmamalı

            ÖZELLİKLE DİKKAT: hiç bir etiket kullanma

            Sadece yorum metnini ver.
"""

            # Gemini API'dan yanıt alma
            response = self.gemini_model.generate_content(prompt)
            comment_text = response.text.strip().replace('"', '').replace("'", "")

            # Kendi kullanıcı adı etiketi kontrolü
            if f"@{own_username}" not in comment_text:
                comment_text += f" @{own_username}"

            # Karakter limiti kontrolü
            if len(comment_text) > 240:
                comment_text = comment_text[:237] + "..."

            return comment_text
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Bağlamsal yorum oluşturma hatası: {e}")
            return f"bunun neresi mantıklı ya ben anlamadım @{own_username}"
        
        
    def send_welcome_dm(self, username: str) -> bool:
        self.driver.get(f"https://x.com/messages/compose?recipient_id={username}")
        time.sleep(random.uniform(1, 2))
        message_box = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='dmComposerTextInput']")
        message = f"Merhaba {username}! Çevrimsiz Deneme Bonusu ve Freespin için profilimizi ziyaret etmeyi unutma!"
        message_box.send_keys(message)
        send_button = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='dmComposerSendButton']")
        send_button.click()
        time.sleep(random.uniform(1, 2))
        return True
    
    def check_ip_change(self) -> bool:
        current_ip = requests.get("https://api.ipify.org").text
        if current_ip != self.last_ip:
            self.last_ip = current_ip
            logger.info(f"IP değişti: {current_ip}")
            return True
        return False
        
        
    @smart_retry
    def perform_retweet_operations(self, max_attempts=5, min_score_threshold=20) -> bool:
        """
        Twitter'da en yüksek etkileşime sahip tweetleri analiz ederek retweet yapar.

        :param max_attempts: Maksimum deneme sayısı
        :param min_score_threshold: Minimum etkileşim skoru eşiği
        :return: Retweet işlemi başarılı mı
        """
        RETWEETED_URLS_FILE = f"retweeted_urls_{self.account.username}.txt"
        attempt_count = 0

        # Daha önce retweet yapılan URL'leri yükle
        retweeted_urls = set()
        if os.path.exists(RETWEETED_URLS_FILE):
            with open(RETWEETED_URLS_FILE, 'r') as f:
                retweeted_urls = set(line.strip() for line in f)
        logger.info(
            f"[{self.account.username}] Toplam {len(retweeted_urls)} retweet kaydı yüklendi")

        while attempt_count < max_attempts:
            attempt_count += 1
            logger.info(
                f"[{self.account.username}] Yüksek etkileşimli tweet retweet analizi başlatılıyor (Deneme {attempt_count}/{max_attempts})")

            try:
                # Ana sayfaya git
                self.driver.get("https://x.com/home?mx=2")
                time.sleep(5)

                analyzed_posts = []

                # Daha kapsamlı tarama - 15 kaydırma yaparak daha fazla post analiz et
                for scroll in range(15):
                    logger.info(
                        f"[{self.account.username}] Sayfa tarama: {scroll + 1}/15")

                    # Görünür gönderileri bul
                    posts = self.find_all_posts()

                    if not posts:
                        logger.warning(
                            f"[{self.account.username}] Hiçbir gönderi bulunamadı, sayfayı kaydırıyorum...")
                        self.driver.execute_script(
                            "window.scrollBy(0, 1000);")
                        time.sleep(3)
                        continue

                    # Gönderileri analiz et
                    for post in posts:
                        try:
                            # URL'i al ve kontrol et
                            tweet_url = self.get_tweet_url(post)
                            if not tweet_url or tweet_url in retweeted_urls:
                                continue

                            # Tweet içeriğini al
                            tweet_text, has_image, image_description = self.get_tweet_content(post)
                            
                            # Her postu skora bakılmaksızın analiz et ve kaydet
                            score = self.calculate_post_score(post)

                            # Minimum skor eşiğini geçiyor mu kontrol et
                            if score < min_score_threshold:
                                continue

                            # Tweet paylaşım zamanını al
                            tweet_date = self.get_tweet_date(post)

                            # Post bilgilerini sakla
                            analyzed_posts.append({
                                'element': post,
                                'url': tweet_url,
                                'text': tweet_text,
                                'score': score,
                                'date': tweet_date['datetime'] if tweet_date else None,
                                'display_date': tweet_date['display_date'] if tweet_date else None
                            })

                            logger.info(
                                f"[{self.account.username}] Yüksek etkileşimli gönderi analiz edildi: URL={tweet_url}, "
                                f"Skor={score:.1f}, "
                                f"Tarih={tweet_date['display_date'] if tweet_date else 'Bilinmiyor'}")

                        except Exception as e:
                            logger.warning(
                                f"[{self.account.username}] Gönderi analizi hatası: {str(e)}")
                            continue

                    # Yeterli sayıda post analiz edildi mi kontrol et
                    if len(analyzed_posts) >= 10:
                        logger.info(
                            f"[{self.account.username}] Yeterli sayıda yüksek etkileşimli post analiz edildi: {len(analyzed_posts)}")
                        break

                    # Sayfayı kaydır ve yeni postlar yüklensin diye bekle
                    self.driver.execute_script("window.scrollBy(0, 1500);")
                    time.sleep(3)  # Yüklenme için bekle

                # Hiç post analiz edilemediyse popüler hesaplara bak
                if not analyzed_posts:
                    logger.warning(
                        f"[{self.account.username}] Ana sayfada yüksek etkileşimli gönderi bulunamadı, popüler hesaplara bakılıyor...")
                        
                    # Popüler hesaplar listesi
                    popular_accounts = ["elonmusk", "cristiano", "YouTube", "kyliejenner", "KimKardashian", 
                                    "selenagomez", "ArianaGrande", "cnnbrk", "Twitter", "ddlovato"]
                                        
                    for account in random.sample(popular_accounts, min(3, len(popular_accounts))):
                        try:
                            self.driver.get(f"https://twitter.com/{account}")
                            time.sleep(5)
                            
                            # Hesabın son tweetlerini bul
                            account_posts = self.find_all_posts()
                            
                            if account_posts:
                                # En fazla 5 tweet analiz et
                                for i, post in enumerate(account_posts[:5]):
                                    # URL'i al ve kontrol et
                                    tweet_url = self.get_tweet_url(post)
                                    if not tweet_url or tweet_url in retweeted_urls:
                                        continue
                                        
                                    # Tweet içeriğini al
                                    tweet_text, has_image, _ = self.get_tweet_content(post)
                                    
                                    # Skoru hesapla
                                    score = self.calculate_post_score(post)
                                    
                                    # Tweet tarihini al
                                    tweet_date = self.get_tweet_date(post)
                                    
                                    # Minimum skor eşiğini kontrol et
                                    if score < min_score_threshold:
                                        continue
                                    
                                    analyzed_posts.append({
                                        'element': post,
                                        'url': tweet_url,
                                        'text': tweet_text,
                                        'score': score,
                                        'date': tweet_date['datetime'] if tweet_date else None,
                                        'display_date': tweet_date['display_date'] if tweet_date else None
                                    })
                                    
                                    logger.info(f"[{self.account.username}] Popüler hesaptan gönderi analiz edildi: @{account}, "
                                            f"URL={tweet_url}, Skor={score:.1f}")
                                
                                if len(analyzed_posts) >= 5:
                                    break
                                    
                        except Exception as e:
                            logger.warning(f"[{self.account.username}] Popüler hesap tarama hatası ({account}): {e}")
                            continue
                
                # Hala hiç post analiz edilemediyse tekrar dene
                if not analyzed_posts:
                    logger.warning(
                        f"[{self.account.username}] Hiç yüksek etkileşimli gönderi analiz edilemedi, yeniden deneniyor...")
                    time.sleep(30)  # Biraz bekle
                    continue

                # Postları skora göre sırala
                analyzed_posts.sort(key=lambda x: x['score'], reverse=True)

                # En iyi postu seç
                best_post = analyzed_posts[0]  # En yüksek skorlu post
                best_url = best_post['url']

                logger.info(
                    f"[{self.account.username}] Retweet için seçilen post: Skor={best_post['score']:.1f}, "
                    f"URL={best_url}, "
                    f"Tarih={best_post['display_date'] if 'display_date' in best_post else 'Bilinmiyor'}")

                # Retweet işlemi
                if self.retweet_post(best_url):
                    # URL'i kaydet ve başarı mesajı
                    with open(RETWEETED_URLS_FILE, 'a') as f:
                        f.write(f"{best_url}\n")
                    logger.info(
                        f"[{self.account.username}] Yüksek etkileşimli post başarıyla retweet edildi: {best_url}")
                    return True
                else:
                    logger.error(
                        f"[{self.account.username}] Retweet işlemi başarısız oldu, yeniden deneniyor...")
                    continue

            except Exception as e:
                logger.error(
                    f"[{self.account.username}] Retweet operasyonu hatası: {e}")
                continue

        logger.error(
            f"[{self.account.username}] Tüm retweet denemeleri başarısız oldu")
        return False
    
    
    def unfollow_daily_users(self, max_unfollows: int = 30) -> bool:
        """
        Günün sonunda bot tarafından takip edilen kullanıcıları takipten çıkarır.
        Takipten çık butonları alt alta sıralı şekilde sırayla işlenir.

        :param max_unfollows: Takipten çıkarılacak maksimum kullanıcı sayısı
        :return: İşlem başarılı mı
        """
        try:
            logger.info(f"[{self.account.username}] Günlük takipten çıkarma işlemi başlatılıyor...")

            # Takip edilen kullanıcılar sayfasına git
            profile_url = f"https://x.com/{self.account.username.replace('@', '')}/following"
            self.driver.get(profile_url)
            time.sleep(5)

            # Takipten çıkarılacak kullanıcıları sıfırla
            unfollowed_count = 0

            while unfollowed_count < max_unfollows:
                try:
                    # Takipten çık butonlarını bul
                    unfollow_buttons_xpath = "//div[@class='css-175oi2r r-1cwvpvk']//button"
                    unfollow_buttons = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_all_elements_located((By.XPATH, unfollow_buttons_xpath))
                    )
                    logger.info(f"[{self.account.username}] {len(unfollow_buttons)} takipten çık butonu bulundu")

                    if not unfollow_buttons:
                        logger.warning(f"[{self.account.username}] Takipten çık butonu bulunamadı, işlem sonlandırılıyor")
                        break

                    # Her butonu sırayla işle
                    for index, button in enumerate(unfollow_buttons, 1):
                        if unfollowed_count >= max_unfollows:
                            break

                        try:
                            # Butonu görünür hale getir
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                            time.sleep(1)

                            # Butona tıkla
                            self.driver.execute_script("arguments[0].click();", button)
                            time.sleep(2)

                            # Onay butonunu bul ve tıkla
                            confirm_button_xpath = "(//button[contains(@class,'css-175oi2r r-sdzlij')])[3]"
                            confirm_button = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, confirm_button_xpath))
                            )
                            self.driver.execute_script("arguments[0].click();", confirm_button)

                            # Takipten çıkarma işlemi başarılı
                            unfollowed_count += 1
                            logger.info(f"[{self.account.username}] {unfollowed_count}/{max_unfollows} kullanıcı takipten çıkarıldı")

                            # Spam algılamasını önlemek için rastgele gecikme
                            time.sleep(random.uniform(3, 6))

                            # Her 5 kullanıcıda bir sayfayı aşağı kaydır
                            if unfollowed_count % 5 == 0:
                                self.driver.execute_script("window.scrollBy(0, 300);")
                                time.sleep(2)  # Yeni içeriğin yüklenmesini bekle

                        except Exception as e:
                            logger.warning(f"[{self.account.username}] Takipten çıkma hatası (buton #{index}): {e}")
                            continue

                    # Eğer yeterli buton işlendiyse veya daha fazla buton yoksa döngüden çık
                    if len(unfollow_buttons) < 5 or unfollowed_count >= max_unfollows:
                        break

                    # Yeni butonların yüklenmesi için sayfayı aşağı kaydır
                    self.driver.execute_script("window.scrollBy(0, 300);")
                    time.sleep(2)

                except Exception as e:
                    logger.error(f"[{self.account.username}] Takipten çıkma işlemi hatası: {e}")
                    break

            # İşlem sonucunu bildir
            if unfollowed_count > 0:
                logger.info(f"[{self.account.username}] Toplam {unfollowed_count} kullanıcı takipten çıkarıldı")
                return True
            else:
                logger.warning(f"[{self.account.username}] Hiç kullanıcı takipten çıkarılamadı")
                return False

        except Exception as e:
            logger.error(f"[{self.account.username}] Takipten çıkarma genel hatası: {e}")
            return False
        
        
    def retweet(self, tweet_url: str) -> bool:
        """
        Belirtilen tweet'i retweet eder.
        
        Args:
            tweet_url (str): Retweet edilecek tweet'in URL'si.
        
        Returns:
            bool: Retweet başarılıysa True, değilse False.
        """
        try:
            self.driver.get(tweet_url)
            time.sleep(random.uniform(1, 2))
            retweet_button = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='retweet']")
            retweet_button.click()
            time.sleep(random.uniform(0.5, 1))
            confirm_button = self.driver.find_element(By.CSS_SELECTOR, "[data-testid='retweetConfirm']")
            confirm_button.click()
            time.sleep(random.uniform(1, 2))
            logger.info(f"{self.username}: Tweet retweet edildi: {tweet_url}")
            return True
        except Exception as e:
            logger.error(f"Retweet sırasında hata: {str(e)}")
            return False
    
    

    def retweet_post(self, post_url):
        """
        Belirtilen URL'deki postu retweet eder

        :param post_url: Retweet edilecek postun URL'i
        :return: İşlem başarılı mı
        """
        try:
            # Direkt olarak URL'e git
            self.driver.get(post_url)
            time.sleep(5)

            # Retweet butonunu bulma ve tıklama
            retweet_button_xpaths = [
                "(//button[@data-testid='retweet'])[1]",
                "(//span[contains(@class,'css-1jxf684 r-1ttztb7')])[2]"
            ]
            
            retweet_clicked = False
            for xpath in retweet_button_xpaths:
                try:
                    retweet_button = self.wait.until(EC.element_to_be_clickable(
                        (By.XPATH, xpath)
                    ))
                    self.driver.execute_script("arguments[0].click();", retweet_button)
                    retweet_clicked = True
                    break
                except Exception:
                    continue
                    
            if not retweet_clicked:
                raise Exception("Retweet butonu bulunamadı")
                
            time.sleep(2)

            # Retweet onay butonuna tıklama
            confirm_button_xpaths = [
                "(//div[contains(@class,'css-146c3p1 r-bcqeeo')])[4]",
                "//div[contains(@class,'css-175oi2r r-1loqt21')]",
                "//div[@data-testid='retweetConfirm']"
            ]
            
            confirm_clicked = False
            for xpath in confirm_button_xpaths:
                try:
                    confirm_button = self.wait.until(EC.element_to_be_clickable(
                        (By.XPATH, xpath)
                    ))
                    self.driver.execute_script("arguments[0].click();", confirm_button)
                    confirm_clicked = True
                    break
                except Exception:
                    continue
            
            if not confirm_clicked:
                raise Exception("Retweet onay butonu bulunamadı")
                
            time.sleep(3)
            
            # Başarı kontrolü yap
            try:
                success_element = self.driver.find_element(By.XPATH, 
                 "//div[contains(text(), 'Retweet') and contains(@aria-label, 'Retweeted')]")
                if success_element:
                    return True
            except Exception:
                # Başarı elementi bulunamadı, farklı bir strateji deneyelim
                try:
                    # Retweet sayacı kontrolü
                    # Eğer sayaç artmışsa muhtemelen başarılı olmuştur
                    retweet_count_before = self.get_interaction_count(
                        self.driver.find_element(By.XPATH, "//article"), 2
                    )
                    time.sleep(1)
                    self.driver.refresh()
                    time.sleep(3)
                    retweet_count_after = self.get_interaction_count(
                        self.driver.find_element(By.XPATH, "//article"), 2
                    )
                    
                    if retweet_count_after >= retweet_count_before:
                        return True
                except Exception:
                    pass
                    
                # En azından işlem sırasında hata olmadıysa başarılı sayalım
                return True

        except Exception as e:
            logger.error(
                f"[{self.account.username}] Retweet işlemi sırasında hata: {str(e)}")
            return False
        
    def wait_for_network_idle(self, timeout: int = 30) -> bool:
        """
        Ağın boşta olmasını bekler (tüm ağ isteklerinin tamamlanması).
        
        :param timeout: Maksimum bekleme süresi (saniye)
        :return: Ağ boşta mı
        """
        try:
            start_time = time.time()
            while time.time() - start_time < timeout:
                pending_requests = self.driver.execute_script(
                    "return window.performance.getEntriesByType('resource').filter(r => !r.responseEnd).length;"
                )
                if pending_requests == 0:
                    return True
                time.sleep(0.5)
            logger.warning(f"[{self.account.username}] Ağ boşta bekleme zaman aşımı")
            return False
        except Exception as e:
            logger.error(f"[{self.account.username}] Ağ boşta bekleme hatası: {e}")
            return False

    def wait_for_operation_complete(self, timeout: int = 10) -> bool:
        """
        İşlemin tamamlanmasını bekler (sayfa stabil olana kadar).
        
        :param timeout: Maksimum bekleme süresi (saniye)
        :return: İşlem tamamlandı mı
        """
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            return True
        except Exception as e:
            logger.warning(f"[{self.account.username}] İşlem tamamlama bekleme hatası: {e}")
            return False
        
    def check_rate_limits(self) -> bool:
        try:
            response = requests.get("https://x.com/home", headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code == 429 or "rate limit" in response.text.lower():
                logger.warning(f"[{self.account.username}] Hız sınırı aşıldı, 15 dakika bekleniyor...")
                time.sleep(15 * 60)
                return False
            return True
        except Exception as e:
            logger.error(f"[{self.account.username}] Hız sınırı kontrol hatası: {e}")
            time.sleep(5 * 60)  # Hata durumunda 5 dakika bekle
            return False
        
    def clear_browser_cache(self) -> None:
        """
        Tarayıcı önbelleğini temizler.
        """
        try:
            self.driver.execute_cdp_cmd("Network.clearBrowserCache", {})
            logger.info(f"[{self.account.username}] Tarayıcı önbelleği temizlendi")
        except Exception as e:
            logger.error(f"[{self.account.username}] Önbellek temizleme hatası: {e}")
        
    
    def perform_quote_tweet(self) -> bool:
        """
        Ana sayfadaki en yüksek etkileşimli gönderiyi analiz eder, içeriği ve yorumları Gemini AI ile okuyarak
        bağlamsal bir alıntı tweet oluşturur ve paylaşır.

        :return: İşlem başarılı mı
        """
        try:
            logger.info(f"[{self.account.username}] Alıntı tweet işlemi başlatılıyor...")

            # Ana sayfaya git
            self.driver.get("https://x.com/home?mx=2")
            time.sleep(5)

            # Postları bul - ilk 20 post
            posts = self.find_all_posts()[:20]

            if not posts:
                logger.warning(f"[{self.account.username}] Hiç post bulunamadı")
                return False

            # Postları analiz et ve puanla
            analyzed_posts = []
            for idx, post in enumerate(posts):
                try:
                    # Tweet içeriğini al
                    tweet_text, has_image, image_description = self.get_tweet_content(post)

                    if not tweet_text:
                        continue

                    # Tweet URL'sini al
                    tweet_url = self.get_tweet_url(post)

                    # Kullanıcı adını al
                    try:
                        username_element = post.find_element(By.XPATH, ".//div[contains(@data-testid, 'User-Name')]//a")
                        profile_handle = username_element.get_attribute('href').split('/')[-1]
                    except:
                        profile_handle = "user"

                    # Etkileşim sayılarını al
                    comment_count = self.get_interaction_count(post, 1)
                    retweet_count = self.get_interaction_count(post, 2)
                    like_count = self.get_interaction_count(post, 3)
                    view_count = self.get_interaction_count(post, 4)

                    # Puanı hesapla
                    score = (comment_count * 5) + (retweet_count * 3) + (like_count * 1)

                    analyzed_posts.append({
                        'index': idx,
                        'element': post,
                        'text': tweet_text,
                        'has_image': has_image,
                        'image_description': image_description,
                        'score': score,
                        'url': tweet_url,
                        'profile_handle': profile_handle,
                        'comment_count': comment_count,
                        'retweet_count': retweet_count,
                        'like_count': like_count,
                        'view_count': view_count
                    })

                    logger.info(f"[{self.account.username}] Tweet #{idx} analiz edildi - Puan: {score}, Metin: {tweet_text[:50]}...")

                except Exception as e:
                    logger.warning(f"[{self.account.username}] Tweet #{idx} analiz hatası: {e}")
                    continue

            if not analyzed_posts:
                logger.warning(f"[{self.account.username}] Hiç tweet analiz edilemedi")
                return False

            # En yüksek puanlı tweet'i seç
            best_post = max(analyzed_posts, key=lambda x: x['score'])

            logger.info(
                f"[{self.account.username}] En yüksek puanlı tweet seçildi - #{best_post['index']}, "
                f"Puan: {best_post['score']}, "
                f"İstatistikler: Yorum: {best_post['comment_count']}, RT: {best_post['retweet_count']}, Beğeni: {best_post['like_count']}, "
                f"Metin: {best_post['text'][:50]}..."
            )

            # Tweete tıkla ve sayfasına git
            try:
                post_element = best_post['element']
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", post_element)
                time.sleep(1)
                self.driver.execute_script("arguments[0].click();", post_element)
                logger.info(f"[{self.account.username}] Seçilen tweet'e tıklandı")
                time.sleep(5)

                # Yorumları topla (en fazla 15)
                existing_comments = []
                max_comments_to_read = 15
                for i in range(1, max_comments_to_read + 1):
                    try:
                        comment_xpath = f"(//div[contains(@class,'css-901oao css-16my406 r-poiln3')])[{i}]"
                        comment_element = self.driver.find_element(By.XPATH, comment_xpath)
                        comment_text = comment_element.text
                        if comment_text and len(comment_text.strip()) > 0:
                            existing_comments.append(comment_text)
                    except Exception:
                        break

                logger.info(f"[{self.account.username}] {len(existing_comments)} yorum toplandı")

                # Gemini AI ile bağlamsal alıntı metni oluştur
                quote_text = self.generate_quote_tweet_text(
                    best_post['text'],
                    best_post['profile_handle'],
                    best_post['has_image'],
                    best_post['image_description'],
                    existing_comments
                )

                # Retweet butonuna tıkla
                try:
                    retweet_button = self.wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "(//div[@class='css-175oi2r r-xoduu5']//div)[4]")
                    ))
                    self.driver.execute_script("arguments[0].click();", retweet_button)
                    logger.info(f"[{self.account.username}] Retweet butonuna tıklandı")
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"[{self.account.username}] Retweet butonu tıklama hatası: {e}")
                    return False

                # Alıntı yap seçeneğine tıkla
                try:
                    quote_option = self.wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "(//a[contains(@class,'css-175oi2r r-18u37iz')])[1]")
                    ))
                    self.driver.execute_script("arguments[0].click();", quote_option)
                    logger.info(f"[{self.account.username}] Alıntı yap seçeneğine tıklandı")
                    time.sleep(3)
                except Exception as e:
                    logger.error(f"[{self.account.username}] Alıntı yap seçeneği tıklama hatası: {e}")
                    return False

                # Alıntı metnini yaz
                try:
                    tweet_box = self.wait.until(EC.presence_of_element_located(
                        (By.XPATH, "//div[@data-testid='tweetTextarea_0']")
                    ))
                    self.driver.execute_script("arguments[0].focus();", tweet_box)
                    for char in quote_text:
                        tweet_box.send_keys(char)
                        time.sleep(random.uniform(0.01, 0.03))
                    logger.info(f"[{self.account.username}] Alıntı metni yazıldı: {quote_text[:50]}...")
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"[{self.account.username}] Alıntı metni yazma hatası: {e}")
                    return False

                # Paylaş butonuna tıkla
                try:
                    submit_button = self.wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//button[@data-testid='tweetButton']")
                    ))
                    self.driver.execute_script("arguments[0].click();", submit_button)
                    logger.info(f"[{self.account.username}] Alıntı tweet paylaşıldı")
                    time.sleep(5)
                    return True
                except Exception as e:
                    logger.error(f"[{self.account.username}] Alıntı tweet paylaşma hatası: {e}")
                    return False

            except Exception as e:
                logger.error(f"[{self.account.username}] Seçili tweet işleme hatası: {e}")
                return False

        except Exception as e:
            logger.error(f"[{self.account.username}] Alıntı tweet işlemi genel hatası: {e}")
            return False
            

    def like_post_comments(self, max_likes: int = random.randint(8, 12)) -> bool:
        """
        Anasayfadaki ilk posta gider, tıklar ve yorumları sırayla beğenir.
        
        :param max_likes: Beğenilecek maksimum yorum sayısı (varsayılan: 8-12)
        :return: İşlem başarılıysa True, değilse False
        """
        try:
            logger.info(f"[{self.account.username}] Yorum beğenme işlemi başlatılıyor...")

            # Hız sınırlarını kontrol et (Twitter/X engelini önlemek için)
            if hasattr(self, 'check_rate_limits') and not self.check_rate_limits():
                logger.warning(f"[{self.account.username}] Hız sınırı aşıldı, işlem iptal edildi")
                return False

            # Anasayfaya git
            logger.debug(f"[{self.account.username}] Anasayfaya yönlendiriliyor...")
            self.driver.get("https://x.com/home")
            time.sleep(random.uniform(4, 6))  # İnsansı gecikme

            # İlk posta tıkla
            first_post_xpath = "(//article[@data-testid='tweet'])[1]"
            try:
                first_post = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, first_post_xpath))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", first_post)
                time.sleep(random.uniform(0.5, 1.5))  # Kısa insansı gecikme
                self.driver.execute_script("arguments[0].click();", first_post)
                time.sleep(random.uniform(2, 4))
                logger.info(f"[{self.account.username}] İlk post başarıyla açıldı")
            except Exception as e:
                logger.error(f"[{self.account.username}] İlk post tıklama hatası: {e}\n{traceback.format_exc()}")
                return False

            # Yorumları beğen
            liked_count = 0
            like_button_index = 1
            max_consecutive_errors = 5
            consecutive_errors = 0

            while liked_count < max_likes:
                try:
                    # Beğen butonunu bul (Twitter/X'in güncel selektörleriyle)
                    like_button_xpath = f"(//button[@data-testid='like' or contains(@aria-label, 'Beğen') or contains(@aria-label, 'Like')])[{like_button_index}]"
                    like_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, like_button_xpath))
                    )

                    # Butonu görünür yap ve tıkla
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", like_button)
                    time.sleep(random.uniform(0.5, 1.5))
                    self.driver.execute_script("arguments[0].click();", like_button)
                    liked_count += 1
                    consecutive_errors = 0  # Hata sayacını sıfırla
                    logger.info(f"[{self.account.username}] {liked_count}/{max_likes} yorum beğenildi")

                    # Spam algılamasını önlemek için rastgele gecikme
                    time.sleep(random.uniform(3, 7))

                    # Her 4 beğenide sayfayı kaydır
                    if liked_count % 4 == 0:
                        self.driver.execute_script("window.scrollBy(0, 300);")
                        time.sleep(random.uniform(1, 2))

                    # Her 10 denemede sayfanın sonuna kaydır (lazy loading için)
                    if like_button_index % 10 == 0:
                        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(random.uniform(1, 3))

                    like_button_index += 1

                except Exception as e:
                    logger.warning(f"[{self.account.username}] Beğenme hatası (buton #{like_button_index}): {e}\n{traceback.format_exc()}")
                    like_button_index += 1
                    consecutive_errors += 1

                    # Arka arkaya fazla hata olursa işlemi sonlandır
                    if consecutive_errors >= max_consecutive_errors:
                        logger.warning(f"[{self.account.username}] Çok fazla hata oluştu, işlem sonlandırılıyor")
                        break

                    time.sleep(random.uniform(1, 3))  # Hata sonrası kısa bekleme

            # İşlem sonucunu bildir
            if liked_count > 0:
                logger.info(f"[{self.account.username}] Toplam {liked_count} yorum beğenildi")
                return True
            else:
                logger.warning(f"[{self.account.username}] Hiç yorum beğenilemedi")
                return False

        except Exception as e:
            logger.error(f"[{self.account.username}] Yorum beğenme genel hatası: {e}\n{traceback.format_exc()}")
            return False
    
    
    

    def generate_quote_tweet_text(self, tweet_text: str, profile_handle: str, has_image: bool,
                             image_description: str, existing_comments: List[str]) -> str:
        """
        Gemini AI kullanarak tweet içeriği, görsel ve yorumlara dayalı bağlamsal alıntı metni oluşturur.

        :param tweet_text: Orijinal tweet metni
        :param profile_handle: Profil kullanıcı adı
        :param has_image: Görsel var mı
        :param image_description: Görsel açıklaması
        :param existing_comments: Toplanan yorumlar
        :return: Oluşturulan alıntı metni
        """
        try:
            if not self.gemini_model:
                return f"Bu paylaşım ilginç! Siz ne düşünüyorsunuz? @{profile_handle}"

            # Yorumları sınırlı sayıda işle
            selected_comments = existing_comments[:5] if len(existing_comments) > 5 else existing_comments
            comments_text = "\n".join([f"- {comment}" for comment in selected_comments]) if selected_comments else "Henüz yorum yok."

            # Görsel bilgisi
            img_info = f"Tweet'teki görsel: {image_description}" if has_image and image_description else "Tweet'te görsel yok."

            prompt = f"""
    Tweet içeriği: "{tweet_text}"
    {img_info}
    Tweet'e yapılmış yorumlar ({len(existing_comments)} yorum):
    {comments_text}

    Görev: Bu tweet için doğal, tartışma yaratacak ve yorumları teşvik edecek bir alıntı metni oluştur.
    Yorum şu özelliklere sahip olmalı:
    1. 100-200 karakter arasında, kısa ve etkili
    2. Doğal, insansı ve samimi bir ton
    3. Tweet içeriğine veya yorumlara bağlamsal referans
    4. Tartışmayı teşvik eden sorular ("Siz ne düşünüyorsunuz?", "Bu doğru mu?") 
    5. Hafif argo veya günlük dil kullanılabilir, abartıya kaçmadan
    6. ASCII karakterleri ve Türkçe harfler kullanılmalı, emoji yok
    7. @{profile_handle} etiketi metnin sonunda yer almalı
    8. Olumsuz veya saldırgan bir algı yaratmamalı
    9. İnsanların yorum yapmasını tetiklemeli

    Örnek:
    Bu analiz çok iddialı, ama haklı olabilir mi? Sizce bu maç nasıl biter? @{profile_handle}
    Vay, bu yorumlar bayağı karışık! Gerçekten bu oranlar tutar mı? Siz ne diyorsunuz? @{profile_handle}

    Sadece metni döndür, açıklama ekleme.
    """
            response = self.gemini_model.generate_content(prompt)
            quote_text = response.text.strip().replace('"', '').replace("'", "")

            # Etiket kontrolü
            if f"@{profile_handle}" not in quote_text:
                quote_text += f" @{profile_handle}"

            # Karakter limiti
            if len(quote_text) > 240:
                quote_text = quote_text[:237] + "..."

            # Özel karakter temizliği
            quote_text = ''.join(c for c in quote_text if ord(c) < 128 or c in 'şŞçÇğĞıİöÖüÜ')

            logger.info(f"[{self.account.username}] Alıntı metni oluşturuldu: {quote_text}")
            return quote_text

        except Exception as e:
            logger.error(f"[{self.account.username}] Alıntı metni oluşturma hatası: {e}")
            return f"Bu paylaşım ilginç! Siz ne düşünüyorsunuz? @{profile_handle}"
        
        
    def perform_follow_operations(self, max_follows: int = 10, max_retries: int = 3) -> bool:
        """
        Yüksek etkileşimli tweetlerin yorumlarına giderek, yorumcuların profillerine gidip takip eder.
        
        :param max_follows: Takip edilecek kullanıcı sayısı
        :param max_retries: Maksimum deneme sayısı
        :return: İşlem başarılı mı
        """
        # Takip edilecek kişi sayısını sabitle
        max_follows = 10
        
        retry_count = 0
        follows_completed = 0
        processed_tweets = set()
        processed_users = set()
        
        while retry_count < max_retries and follows_completed < max_follows:
            try:
                logger.info(f"[{self.account.username}] Yüksek etkileşimli tweet aranıyor... Deneme: {retry_count+1}/{max_retries}")
                
                # Ana sayfaya git
                self.driver.get("https://x.com/home?mx=2")
                time.sleep(5)
                
                # Tweetleri bul
                posts = self.find_all_posts()
                
                if not posts:
                    logger.warning(f"[{self.account.username}] Hiçbir tweet bulunamadı.")
                    retry_count += 1
                    continue
                    
                # Tüm tweetleri analiz et
                analyzed_tweets = []
                
                for post in posts:
                    try:
                        # Tweet içeriğini al
                        tweet_text, has_image, _ = self.get_tweet_content(post)
                        
                        # Tweet URL'ini al
                        tweet_url = self.get_tweet_url(post)
                        if not tweet_url or tweet_url in processed_tweets:
                            continue
                        
                        # Etkileşim skorunu hesapla
                        score = self.calculate_post_score(post)
                        
                        analyzed_tweets.append({
                            'element': post,
                            'text': tweet_text,
                            'score': score,
                            'url': tweet_url
                        })
                        
                    except Exception as e:
                        logger.debug(f"[{self.account.username}] Tweet analizi hatası: {e}")
                
                # Tweet bulunamadıysa yeniden dene
                if not analyzed_tweets:
                    logger.warning(f"[{self.account.username}] Analiz edilebilir tweet bulunamadı.")
                    retry_count += 1
                    continue
                    
                # Tweetleri skora göre azalan sırada sırala
                analyzed_tweets.sort(key=lambda x: x['score'], reverse=True)
                
                logger.info(f"[{self.account.username}] {len(analyzed_tweets)} tweet analiz edildi, en yüksek skorlu {min(5, len(analyzed_tweets))} tanesi işlenecek")
                
                # En yüksek etkileşimli tweetleri işle
                for tweet_data in analyzed_tweets[:5]:
                    if follows_completed >= max_follows:
                        break
                        
                    # Tweet URL'sini işlenmiş olarak işaretle
                    processed_tweets.add(tweet_data['url'])
                    
                    # Tweet'e git
                    logger.info(f"[{self.account.username}] Yüksek etkileşimli tweet'e gidiliyor (Skor: {tweet_data['score']}): {tweet_data['url']}")
                    self.driver.get(tweet_data['url'])
                    time.sleep(5)
                    
                    # Hedef tweet URL'sini kaydet - geri dönmek için
                    target_tweet_url = tweet_data['url']
                    
                    # Yorumlar için indeks ayarla
                    comment_index = 2  # İlk yorum indeksi
                    max_comment_index = 10  # Maksimum kontrol edilecek yorum sayısı
                    
                    # Her yoruma tek tek git ve yorumcu profillerine eriş
                    while comment_index <= max_comment_index and follows_completed < max_follows:
                        try:
                            # Yorum tweet'ine tıkla (XPath indeksi 1'den başlar)
                            comment_xpath = f"(//article[@role='article'])[{comment_index}]"
                            logger.info(f"[{self.account.username}] Yorum elemeni aranıyor: {comment_xpath}")
                            
                            try:
                                # Yorum elementini bul ve görünür kıl
                                comment_element = WebDriverWait(self.driver, 10).until(
                                    EC.presence_of_element_located((By.XPATH, comment_xpath))
                                )
                                
                                # Elementi görünür yap
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", comment_element)
                                time.sleep(1)
                                
                                # Yoruma tıkla
                                self.driver.execute_script("arguments[0].click();", comment_element)
                                time.sleep(5)
                                
                                # Şu anki URL'yi al ve kullanıcı adını çıkar
                                current_url = self.driver.current_url
                                
                                if '/status/' in current_url:
                                    # URL'den kullanıcı adını çıkar
                                    username = current_url.split('/status/')[0].split('/')[-1]
                                    logger.info(f"[{self.account.username}] Yorum URL'sinden kullanıcı adı çıkarıldı: {username}")
                                    
                                    # Daha önce işlenmiş mi kontrol et
                                    if username.lower() not in processed_users:
                                        # Kullanıcı profiline doğrudan git
                                        profile_url = f"https://x.com/{username}"
                                        self.driver.get(profile_url)
                                        time.sleep(5)
                                        
                                        # Takip et butonları
                                        follow_button_xpaths = [
                                            "(//span[text()='Follow'])[1]",
                                            "(//span[contains(@class,'css-1jxf684 r-dnmrzs')]//span)[3]",
                                            "//div[@role='button']//span[text()='Follow']", 
                                            "//div[@data-testid='follow']",
                                            "//div[contains(@aria-label, 'Follow') and not(contains(@aria-label, 'Following'))]",
                                            "//span[text()='Follow']//ancestor::div[@role='button']",
                                            "//span[contains(text(),'Follow')]//ancestor::div[@data-testid='follow']"
                                        ]
                                        
                                        follow_clicked = False
                                        for xpath in follow_button_xpaths:
                                            try:
                                                # Bu profilin takip edilebilirliğini kontrol et
                                                if "This account doesn't exist" in self.driver.page_source or "Account suspended" in self.driver.page_source:
                                                    logger.warning(f"[{self.account.username}] Kullanıcı {username} mevcut değil veya askıya alınmış, geçiliyor")
                                                    break
                                                
                                                follow_button = WebDriverWait(self.driver, 5).until(
                                                    EC.element_to_be_clickable((By.XPATH, xpath))
                                                )
                                                # JavaScript ile tıkla
                                                self.driver.execute_script("arguments[0].click();", follow_button)
                                                follow_clicked = True
                                                follows_completed += 1
                                                processed_users.add(username.lower())
                                                
                                                logger.info(f"[{self.account.username}] Kullanıcı {username} takip edildi! ({follows_completed}/{max_follows})")
                                                
                                                # Takip işlemi tamamlandıktan sonra biraz bekle
                                                time.sleep(3)
                                                break
                                            except Exception as e:
                                                logger.debug(f"[{self.account.username}] Takip butonu tıklama hatası ({xpath}): {e}")
                                                continue
                                        
                                        if not follow_clicked:
                                            logger.warning(f"[{self.account.username}] Kullanıcı {username} için takip butonu tıklanamadı.")
                                    
                                    else:
                                        logger.info(f"[{self.account.username}] Kullanıcı {username} daha önce işlendi, geçiliyor.")
                                
                                # Hedef tweet'e geri dön
                                self.driver.get(target_tweet_url)
                                time.sleep(5)
                                
                            except Exception as e:
                                logger.warning(f"[{self.account.username}] Yorum {comment_index} bulunamadı: {e}")
                        
                        except Exception as e:
                            logger.warning(f"[{self.account.username}] Yorum işleme hatası: {e}")
                        
                        # Bir sonraki yoruma geç
                        comment_index += 1
                    
                    # Bu tweet'teki yorumcular takip edildi mi kontrol et
                    if follows_completed >= max_follows:
                        logger.info(f"[{self.account.username}] Hedef takip sayısına ulaşıldı! ({follows_completed}/{max_follows})")
                        break
                
                # Tüm tweetler işlendikten sonra hedef sayıya ulaşılamadıysa
                if follows_completed < max_follows:
                    retry_count += 1
                    logger.info(f"[{self.account.username}] Hedef takip sayısına ulaşılamadı ({follows_completed}/{max_follows}), yeni tweetler aranıyor.")
                    # Bir sonraki deneme için bekle
                    time.sleep(3)
                    
            except Exception as e:
                logger.error(f"[{self.account.username}] Takip işlemi genel hatası: {e}")
                retry_count += 1
                time.sleep(3)
        
        # Takip işlemi sonuç kontrolü
        if follows_completed > 0:
            logger.info(f"[{self.account.username}] Takip işlemi tamamlandı: {follows_completed} kullanıcı takip edildi.")
            return True
        else:
            logger.warning(f"[{self.account.username}] Takip işlemi tamamlanamadı. Hiç kullanıcı takip edilemedi.")
            return False



    def find_targeted_accounts(self, niche="betting"):
        """
        Belirli bir niş için hedef hesapları bulur
        
        :param niche: Hedef niş/kategori
        :return: Hedef hesaplar listesi
        """
        try:
            # Niş kategoriye göre arama terimleri
            search_terms = {
                "betting": ["bahis", "casino", "bet", "slot", "jackpot"],
                "sports": ["spor", "futbol", "basketbol", "maç", "iddaa"],
                "finance": ["finans", "borsa", "yatırım", "kripto", "forex"]
            }
            
            terms = search_terms.get(niche, ["bahis"])
            targeted_accounts = []
            
            # Aramak için rastgele bir terim seç
            search_term = random.choice(terms)
            logger.info(f"[{self.account.username}] Hedef {niche} hesapları için '{search_term}' aranıyor")
            
            # Twitter'da arama yap
            self.driver.get(f"https://twitter.com/search?q={search_term}&src=typed_query&f=user")
            time.sleep(5)
            
            # Hesapları bul
            account_elements = self.driver.find_elements(By.XPATH, "//div[@data-testid='cellInnerDiv']")
            
            for element in account_elements[:15]:  # En fazla 15 hesabı incele
                try:
                    # Kullanıcı adını al
                    username_element = element.find_element(By.XPATH, ".//div[contains(@class, 'css-1rynq56 r-bcqeeo r-qvutc0 r-37j5jr')]/span")
                    username = username_element.text.replace("@", "")
                    
                    # Biyografiyi al
                    try:
                        bio_element = element.find_element(By.XPATH, ".//div[contains(@class, 'css-1dbjc4n r-1adg3ll')]/div")
                        bio = bio_element.text
                    except:
                        bio = ""
                    
                    # Hedef nişe uygun mu kontrol et
                    is_targeted = False
                    for term in terms:
                        if term.lower() in bio.lower() or term.lower() in username.lower():
                            is_targeted = True
                            break
                    
                    if is_targeted:
                        targeted_accounts.append(username)
                except Exception as e:
                    logger.debug(f"[{self.account.username}] Hesap analizi hatası: {e}")
            
            logger.info(f"[{self.account.username}] {len(targeted_accounts)} adet {niche} hesabı bulundu")
            return targeted_accounts
            
        except Exception as e:
            logger.error(f"[{self.account.username}] Hedef hesap bulma hatası: {e}")
            # Yedek hesap listesi döndür
            return ["iddaa", "nesine", "tuttur", "misli", "bilyoner"]
        
        
    def close(self):
        """Tarayıcıyı kapatır"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info(
                    f"[{self.account.username}] Tarayıcı başarıyla kapatıldı")
            except Exception as e:
                logger.error(
                    f"[{self.account.username}] Tarayıcı kapatma hatası: {e}")
                
                


def main():
    """
    Bot'un ana çalışma döngüsünü yöneten ana fonksiyon.
    Twitter hesapları için bahis/casino içerikli tweet gönderme, yorum, retweet, takip ve 
    topluluk etkileşimlerini gerçekleştirir.
    Tüm işlemleri 30 saate yayarak spam olarak algılanmayı engeller.
    Günün sonunda takip ettiği hesapları takipten çıkarır.
    """
    # Hesap yapılandırması
    accounts = [
        TwitterAccount(username="@1kingbet", password="askedsiker"),
        TwitterAccount(username="@Bet1king", password="sheimmedia2"),
        TwitterAccount(username="@1king_casino", password="sheimmedia2"),
        TwitterAccount(username="@1kingbetss", password="sheimmedia2"),
        TwitterAccount(username="AloBetOfficial", password="sheimmedia1"),
        TwitterAccount(username="alobetguncell", password="sheimmedia1"),
        TwitterAccount(username="alobetcasino", password="sheimmedia1"),
        TwitterAccount(username="alobetgiris", password="sheimmedia1"),

        # İsterseniz daha fazla hesap ekleyebilirsiniz
    ]

    # Hesaplar arası zaman takibi
    last_account_action_time = {}
    # Her hesap için son eylem zamanını başlangıçta ayarla
    for account in accounts:
        # Başlangıçta farklı zamanlarda başlasınlar diye her hesaba rastgele bir zaman ata
        last_account_action_time = {acc.username: time.time() - random.randint(0, 7200) for acc in accounts}
        account_last_actions = {acc.username: None for acc in accounts}

    # Gemini API anahtarı
    GEMINI_API_KEY = "AIzaSyD4j_CmWgUVKvLQ9Ar1i0by13ZKuDNxFEQ"  # API anahtarınızı buraya girin

    # Tarayıcı örnekleri
    browser_instances = {}

    # Hesap aktivite takibi için sözlük
    account_activities = {}

    # 30 saatlik döngü için sabitler (saniye cinsinden)
    CYCLE_TIME = 30 * 3600  # 30 saat = 108,000 saniye

    # İşlem aralıkları için diziler oluştur
    # Tüm 30 saatlik döngüyü kapsayan zaman pencereleri tanımla
    
    # Tüm işlem tiplerinin döngü boyunca rastgele zaman pencerelerini oluştur
    # Her işlem tipi için 3 farklı zaman penceresi tanımla
    def create_time_windows(num_windows: int = None) -> list:
        if num_windows is None:
            num_windows = random.randint(3, 5)  # Daha fazla pencere
        windows = []
        day_fraction = 1.0 / num_windows
        for i in range(num_windows):
            start = i * day_fraction + random.uniform(0, day_fraction * 0.4)
            end = start + random.uniform(0.1, 0.15)  # Daha geniş pencereler
            if end > 1.0:
                end = 1.0
            windows.append((start, end))
        return windows

    # Her işlem türü için rastgele zaman pencereleri oluştur
    tweet_windows = create_time_windows()
    comment_windows = create_time_windows()
    follow_windows = create_time_windows()
    retweet_windows = create_time_windows()
    tweet_analysis_windows = create_time_windows()
    strategy_windows = create_time_windows()

    # Son işlem türünü saklayan değişken
    last_action_type = None

    # Her hesap için günlük limitler ve zaman pencerelerini oluştur
    # main fonksiyonu içinde, account_activities oluşturulurken:
    for account in accounts:
        account_activities[account.username] = {
            'tweets': {
                'count': 0,
                'limit': random.randint(4, 6),
                'windows': tweet_windows,
                'last_action': 0
            },
            'comments': {
                'count': 0,
                'limit': random.randint(8, 12),
                'windows': comment_windows,
                'last_action': 0
            },
            'follows': {
                'count': 0,
                'limit': random.randint(6, 8),
                'windows': follow_windows,
                'last_action': 0
            },
            'retweets': {
                'count': 0,
                'limit': random.randint(1, 2),
                'windows': retweet_windows,
                'last_action': 0
            },
            'tweet_analysis': {
                'count': 0,
                'limit': 2,
                'windows': tweet_analysis_windows,
                'last_action': 0,
                'morning_done': False,
                'afternoon_done': False,
                'evening_done': False
            },
            'strategy': {
                'count': 0,
                'limit': 2,
                'windows': strategy_windows,
                'last_action': 0
            },
            'quote_tweet': {
                'count': 0,
                'limit': random.randint(2, 3),
                'windows': create_time_windows(),
                'last_action': 0
            },
            'comment_likes': {  # Yeni özellik
                'count': 0,
                'limit': random.randint(2, 3),  # Günde 2-4 kez
                'windows': create_time_windows(),
                'last_action': 0
            },
            'contest_tweet': {  # Yeni özellik
                'count': 0,
                'limit': random.randint(0, 1),  # Günde 2-4 kez
                'windows': create_time_windows(),
                'last_action': 0
            },
            'unfollow_done': False,
            'cycle_start': time.time(),
            'min_action_gap': 20 * 60
        }

    # Her hesabın en son yaptığı işlemi takip eden sözlük
    account_last_actions = {acc.username: None for acc in accounts}

    # Tüm hesapları başlatma
    for account in accounts:
        try:
            bot = TwitterBot(account, GEMINI_API_KEY)
            if bot.login():
                browser_instances[account.username] = bot
                logger.info(f"{account.username} başarıyla başlatıldı")
            else:
                logger.error(f"{account.username} başlatılamadı")
        except Exception as e:
            logger.error(f"{account.username} başlatma hatası: {e}")

    # En son işlem yapılan hesabı sakla
    last_used_account = None

    try:
        while True:
            # Aktif hesapların listesini oluştur
            active_accounts = [acc for acc in accounts if acc.username in browser_instances]

            if not active_accounts:
                logger.error("Aktif hesap kalmadı!")
                break

            # Seçilebilir hesapları belirle
            eligible_accounts = []
            current_time = time.time()

            # Her hesap için seçilebilir olup olmadığını kontrol et
            for account in active_accounts:
                activities = account_activities[account.username]
                cycle_elapsed = current_time - activities['cycle_start']
                
                # 24 saatlik süre dolduysa ve takipten çıkarma işlemi henüz yapılmadıysa
                if cycle_elapsed >= CYCLE_TIME * 0.95 and not activities.get('unfollow_done', False):
                    # Takipten çıkarma işlemini yap
                    bot = browser_instances[account.username]
                    try:
                        logger.info(f"{account.username} için 24 saatlik döngü sonunda takipten çıkarma işlemi başlatılıyor...")
                        if hasattr(bot, 'unfollow_daily_users'):
                            if bot.unfollow_daily_users(max_unfollows=30):
                                activities['unfollow_done'] = True
                                logger.info(f"{account.username} için takipten çıkarma işlemi başarıyla tamamlandı")
                            else:
                                logger.warning(f"{account.username} için takipten çıkarma işlemi başarısız oldu")
                        else:
                            logger.error(f"{account.username} botunda 'unfollow_daily_users' fonksiyonu tanımlı değil!")
                    except Exception as e:
                        logger.error(f"{account.username} için takipten çıkarma işlemi hatası: {e}")

                # 24 saatlik süre dolduğunda döngüyü sıfırla
                if cycle_elapsed >= CYCLE_TIME:
                    # Tüm işlem sayaçlarını sıfırla
                    for action_type in ['tweets', 'comments', 'follows', 'retweets', 'tweet_analysis', 'strategy', 'quote_tweet']:
                        activities[activity]['count'] = 0
                        activities[activity]['last_action'] = 0
                        # Limitleri yeniden belirle
                        if activity == 'tweets':
                            activities[activity]['limit'] = random.randint(3, 5)
                        elif activity == 'comments':
                            activities[activity]['limit'] = random.randint(5, 10)
                        elif activity == 'follows':
                            activities[activity]['limit'] = random.randint(7, 10)
                        elif activity == 'quote_tweet':
                            activities[activity]['limit'] = random.randint(2, 3)
                        elif activity == 'retweets':
                            activities[activity]['limit'] = random.randint(1, 3)
                        elif activity == 'tweet_analysis':
                            activities[activity]['limit'] = 2
                            activities[activity]['morning_done'] = False
                            activities[activity]['afternoon_done'] = False
                            activities[activity]['evening_done'] = False
                        elif activity == 'strategy':
                            activities[activity]['limit'] = 2

                    # Takipten çıkarma işlemi bayrağını sıfırla
                    activities['unfollow_done'] = False

                    # Yeni zaman pencerelerini ayarla
                    activities['tweets']['windows'] = create_time_windows()
                    activities['comments']['windows'] = create_time_windows()
                    activities['follows']['windows'] = create_time_windows()
                    activities['retweets']['windows'] = create_time_windows()
                    activities['tweet_analysis']['windows'] = create_time_windows()
                    activities['strategy']['windows'] = create_time_windows()

                    # Yeni döngü başlangıcını ayarla
                    activities['cycle_start'] = current_time
                    logger.info(f"{account.username} için 24 saatlik döngü yenilendi.")
                    cycle_elapsed = 0  # Döngü süresi sıfırlandı

                # Son işlemden bu yana geçen süreyi kontrol et
                last_any_action = max([activities[act]['last_action'] for act in [
                    'tweets', 'comments', 'follows', 'retweets', 'tweet_analysis', 'strategy', 'quote_tweet']])
                time_since_last_action = current_time - last_any_action if last_any_action > 0 else float('inf')
                
                # İşlemler arası minimum bekleme süresi geçtiyse hesap uygun
                if time_since_last_action >= activities['min_action_gap']:
                    eligible_accounts.append(account)
                else:
                    logger.debug(f"{account.username} için minimum bekleme süresi henüz dolmadı. Kalan: {activities['min_action_gap'] - time_since_last_action:.1f} saniye")

            # Eğer seçilebilir hesap yoksa bekle
            if not eligible_accounts:
                wait_time = 60  # 1 dakika bekle
                logger.info(f"Seçilebilir hesap yok. {wait_time // 60} dakika bekleniyor...")
                time.sleep(wait_time)
                continue

            # Seçilebilir hesaplardan birini seç
            account = random.choice(eligible_accounts)
            activities = account_activities[account.username]

            # Şu anki döngüdeki ilerleme
            current_time = time.time()
            cycle_elapsed = current_time - activities['cycle_start']
            cycle_progress = cycle_elapsed / CYCLE_TIME

            # Mevcut saat - Tweet analizi için sabah, öğle, akşam ayrımı
            current_hour = datetime.now().hour
            is_morning = 6 <= current_hour < 12
            is_afternoon = 12 <= current_hour < 18
            is_evening = (18 <= current_hour < 24) or (0 <= current_hour < 6)

            # Yapılabilecek işlemleri belirle
            available_actions = []

            # Her eylem için, eğer limit dolmadıysa ve son yapılan işlemle aynı değilse listeye ekle
            for action_type in ['tweets', 'comments', 'follows', 'retweets', 'tweet_analysis', 'strategy', 'quote_tweet']:
                action_data = activities[action_type]

                # Eylem limitini kontrol et
                if action_data['count'] >= action_data['limit']:
                    logger.debug(f"{account.username} için {action_type} limiti doldu: {action_data['count']}/{action_data['limit']}")
                    continue
                
                # Son yapılan işlemle aynı işlemi tekrar yapma
                if account_last_actions.get(account.username) == action_type:
                    logger.debug(f"{account.username} için {action_type} son işlem olduğu için atlandı")
                    continue
                
                # Tweet analizi için sabah, öğle, akşam kontrolü
                if action_type == 'tweet_analysis':
                    # Sabah, öğle, akşam farklı slotlar için
                    if (is_morning and activities['tweet_analysis'].get('morning_done', False) is False) or \
                       (is_afternoon and activities['tweet_analysis'].get('afternoon_done', False) is False) or \
                       (is_evening and activities['tweet_analysis'].get('evening_done', False) is False):
                        pass  # Bu koşul sağlanıyorsa devam et, yoksa atla
                    else:
                        logger.debug(f"{account.username} için tweet_analysis uygun zaman dilimi değil")
                        continue  # Zamanlamaya uygun değilse bu işlemi atla

                # Eylem için uygun zaman penceresinde miyiz kontrol et
                in_time_window = False
                for window_start, window_end in action_data['windows']:
                    if window_start <= cycle_progress <= window_end:
                        in_time_window = True
                        break

                # main fonksiyonu içinde, available_actions oluşturulurken:
                if in_time_window:
                    if action_type == 'tweets':
                        available_actions.append('tweet')
                    elif action_type == 'comments':
                        available_actions.append('comment')
                    elif action_type == 'follows':
                        available_actions.append('follow')
                    elif action_type == 'retweets':
                        available_actions.append('retweet')
                    elif action_type == 'tweet_analysis':
                        available_actions.append('tweet_analysis')
                    elif action_type == 'strategy':
                        available_actions.append('strategy')
                    elif action_type == 'quote_tweet':
                        available_actions.append('quote_tweet')
                    elif action_type == 'comment_likes':  # Yeni özellik
                        available_actions.append('comment_likes')

            # Eğer hiç uygun işlem bulunamadıysa, limiti dolmamış tüm işlemlerden seçim yap
            if not available_actions:
                logger.info(f"{account.username} için uygun zaman penceresi bulunamadı. Tüm işlemler kontrol ediliyor...")
                for action_type in ['tweets', 'comments', 'follows', 'retweets', 'tweet_analysis', 'strategy', 'quote_tweet', 'comment_likes']:
                    action_data = activities[action_type]
                    if action_data['count'] < action_data['limit'] and account_last_actions.get(account.username) != action_type:
                        if action_type == 'tweets':
                            available_actions.append('tweet')
                        elif action_type == 'comments':
                            available_actions.append('comment')
                        elif action_type == 'follows':
                            available_actions.append('follow')
                        elif action_type == 'retweets':
                            available_actions.append('retweet')
                        elif action_type == 'tweet_analysis':
                            available_actions.append('tweet_analysis')
                        elif action_type == 'strategy':
                            available_actions.append('strategy')
                        elif action_type == 'quote_tweet':
                            available_actions.append('quote_tweet')
                        elif action_type == 'comment_likes':  # Yeni özellik
                            available_actions.append('comment_likes')
                        
                if available_actions:
                    logger.info(f"Uygun zaman penceresi bulunamadı, tüm mevcut işlemler eklendi: {available_actions}")

            # Yapılabilecek işlem yoksa bu döngüyü atla
            if not available_actions:
                logger.info(f"{account.username} için şu anda uygun işlem yok. (Döngü ilerlemesi: %{cycle_progress*100:.1f})")
                time.sleep(60)  # 1 dakika bekle
                continue

            # Rastgele bir işlem seç
            action = random.choice(available_actions)
            bot = browser_instances[account.username]

            logger.info(f"Hesap seçildi: {account.username}, Yapılacak İşlem: {action} (Döngü ilerlemesi: %{cycle_progress*100:.1f})")

            # İşlem zamanını kaydet
            current_time = time.time()

            # Son yapılan işlemi kaydet
            account_last_actions[account.username] = action.replace('tweet', 'tweets').replace('comment', 'comments').replace('follow', 'follows').replace('retweet', 'retweets')

            # İşlemle ilgili saati kaydet (tweet analizi için)
            if action == 'tweet_analysis':
                if is_morning:
                    activities['tweet_analysis']['morning_done'] = True
                elif is_afternoon:
                    activities['tweet_analysis']['afternoon_done'] = True
                elif is_evening:
                    activities['tweet_analysis']['evening_done'] = True

            # Seçilen işlemi uygula
            try:
                if action == 'tweet':
                    # Önce JSON dosyasından tweet önerilerini dene
                    tweet_suggestions = bot.load_tweet_suggestions_from_json()
                    
                    if tweet_suggestions and len(tweet_suggestions) > 0:
                        # Rastgele bir öneri seç
                        tweet_message = random.choice(tweet_suggestions)
                        if bot.post_tweet(tweet_message):
                            activities['tweets']['count'] += 1
                            activities['tweets']['last_action'] = current_time
                            logger.info(f"{account.username} için analiz bazlı tweet gönderildi! ({activities['tweets']['count']}/{activities['tweets']['limit']})")
                    else:
                        # JSON'dan öneri bulunamazsa Gemini AI kullan
                        tweet_messages = bot.generate_ai_betting_tweets(num_tweets=1, betting_theme="mixed")
                        if tweet_messages and len(tweet_messages) > 0:
                            if bot.post_tweet(tweet_messages[0]):
                                activities['tweets']['count'] += 1
                                activities['tweets']['last_action'] = current_time
                                logger.info(f"{account.username} için AI tweet gönderildi! ({activities['tweets']['count']}/{activities['tweets']['limit']})")

                elif action == 'comment':
                    logger.info(f"{account.username} için yorum işlemi başlatılıyor...")
                    
                    if hasattr(bot, 'perform_community_interactions'):
                        try:
                            result = bot.perform_community_interactions()
                            logger.info(f"Yorum fonksiyonu sonucu: {result}")
                            if result:
                                activities['comments']['count'] += 1
                                activities['comments']['last_action'] = current_time
                                logger.info(f"{account.username} için yorum yapıldı!")
                            else:
                                logger.warning(f"{account.username} için yorum yapılamadı!")
                        except Exception as e:
                            logger.error(f"Yorum fonksiyonu çağrısı sırasında hata: {e}")
                    else:
                        logger.error(f"{account.username} botunda 'perform_community_interactions' fonksiyonu tanımlı değil!")

                elif action == 'follow':
                    follows_per_session = min(random.randint(
                        2, 4), activities['follows']['limit'] - activities['follows']['count'])
                    if bot.perform_follow_operations(max_follows=follows_per_session):
                        activities['follows']['count'] += follows_per_session
                        activities['follows']['last_action'] = current_time
                        logger.info(
                            f"{account.username} için {follows_per_session} bahis hesabı takip işlemi yapıldı! ({activities['follows']['count']}/{activities['follows']['limit']})")

                elif action == 'retweet':
                    if bot.perform_retweet_operations():
                        activities['retweets']['count'] += 1
                        activities['retweets']['last_action'] = current_time
                        logger.info(
                            f"{account.username} için bahis içerikli retweet yapıldı! ({activities['retweets']['count']}/{activities['retweets']['limit']})")

                


                elif action == 'tweet_analysis':
                    if bot.collect_and_analyze_tweets(max_tweets=30, min_likes=10):
                        activities['tweet_analysis']['count'] += 1
                        activities['tweet_analysis']['last_action'] = current_time
                        logger.info(
                            f"{account.username} için bahis tweet analizi yapıldı! ({activities['tweet_analysis']['count']}/{activities['tweet_analysis']['limit']})")

                elif action == 'strategy':
                    # Gemini AI ile strateji güncelleme
                    if hasattr(bot, 'ai_driven_casino_strategy'):
                        bot.ai_driven_casino_strategy()
                        activities['strategy']['count'] += 1
                        activities['strategy']['last_action'] = current_time
                        logger.info(
                            f"{account.username} için Gemini AI bahis stratejisi güncellendi! ({activities['strategy']['count']}/{activities['strategy']['limit']})")
                    else:
                        logger.error(f"{account.username} botunda 'ai_driven_casino_strategy' fonksiyonu tanımlı değil!")


                elif action == 'quote_tweet':
                    logger.info(f"{account.username} için alıntı tweet işlemi başlatılıyor...")
                    if hasattr(bot, 'perform_quote_tweet'):
                        try:
                            if bot.perform_quote_tweet():
                                activities['quote_tweet']['count'] += 1
                                activities['quote_tweet']['last_action'] = current_time
                                logger.info(f"{account.username} için alıntı tweet yapıldı! ({activities['quote_tweet']['count']}/{activities['quote_tweet']['limit']})")
                            else:
                                logger.warning(f"{account.username} için alıntı tweet yapılamadı!")
                        except Exception as e:
                            logger.error(f"{account.username} için alıntı tweet hatası: {e}")
                    else:
                        logger.error(f"{account.username} botunda 'perform_quote_tweet' fonksiyonu tanımlı değil!")
                        
                if action == 'comment_likes':
                    logger.info(f"{account.username} için yorum beğenme işlemi başlatılıyor...")
                    if hasattr(bot, 'like_post_comments'):
                        try:
                            if bot.like_post_comments():
                                activities['comment_likes']['count'] += 1
                                activities['comment_likes']['last_action'] = current_time
                                logger.info(f"{account.username} için yorum beğenme yapıldı! ({activities['comment_likes']['count']}/{activities['comment_likes']['limit']})")
                            else:
                                logger.warning(f"{account.username} için yorum beğenme yapılamadı!")
                        except Exception as e:
                            logger.error(f"{account.username} için yorum beğenme hatası: {e}")
                    else:
                        logger.error(f"{account.username} botunda 'like_post_comments' fonksiyonu tanımlı değil!")


            except Exception as e:
                logger.error(
                    f"{account.username} için {action} işlemi sırasında hata: {e}")
                
            cycle_progress = cycle_elapsed / CYCLE_TIME
            if cycle_progress >= 0.933 and not activities.get('unfollow_done', False):  # 28/30 saat
                bot = browser_instances[account.username]
                if bot.unfollow_daily_users(max_unfollows=30):
                    activities['unfollow_done'] = True
                    logger.info(f"{account.username} için takipten çıkarma işlemi tamamlandı")
                    
            if cycle_progress >= 0.4 and activities['contest_tweet']['count'] < 1 and time.strftime("%A") == "Tuesday":  # Salı 12:00 civarı
                event = "Lakers-Celtics maçı" if time.strftime("%Y-%m-%d") == "2025-05-20" else None
                if bot.post_contest_tweet(event=event, hashtags=["#Bahis", "#NBA"], use_poll=bool(random.random() < 0.3)):
                    activities['contest_tweet']['count'] += 1
                    logger.info(f"{account.username}: Yarışma tweet'i gönderildi")
                    
            if cycle_progress >= 0.4 and activities['contest_tweet']['count'] < 1 and time.strftime("%A") == "Tuesday":  # Salı 12:00 civarı
                if bot.check_rate_limits():  # Hız sınırı kontrolü
                    if bot.post_contest_tweet(hashtags=["#Bahis", "#AloBet", "#Kupon", "#SporBonus"], reward_count=2):  # 2 kazanan
                        activities['contest_tweet']['count'] += 1
                        logger.info(f"{account.username}: Kupon yarışma tweet'i gönderildi")
                        
                        
                        # Çapraz retweet işlemi
                        for other_account in accounts:
                            if other_account.username != account.username and random.random() < 0.3:
                                other_bot = browser_instances[other_account.username]
                                if other_bot.check_rate_limits():
                                    time.sleep(random.uniform(300, 900))  # 5-15 dakika bekle
                                    success = other_bot.retweet(tweet_url=activities['contest_tweet']['url'])
                                    if success:
                                        logger.info(f"{other_account.username} tarafından {account.username} yarışma tweet'i retweet edildi")
                                    else:
                                        logger.error(f"{other_account.username} retweet yapamadı")

            # Gün değiştiğinde tweet analizi işaretlerini sıfırla
            now = datetime.now()
            if now.hour == 0 and now.minute < 10:  # Gece yarısından sonraki ilk 10 dakika
                for acc in active_accounts:
                    act = account_activities[acc.username]
                    if 'tweet_analysis' in act:
                        act['tweet_analysis']['morning_done'] = False
                        act['tweet_analysis']['afternoon_done'] = False
                        act['tweet_analysis']['evening_done'] = False
                        logger.info(f"{acc.username} için tweet analizi işaretleri sıfırlandı")

            # Hesaplar arası bekleme süresi
            wait_time = random.randint(1 * 60, 5 * 60)  # 1-5 dakika arası
            logger.info(f"İşlem tamamlandı. {wait_time // 60} dakika bekleniyor...")
            time.sleep(wait_time)


    except KeyboardInterrupt:
        logger.info("Bot kullanıcı tarafından durduruldu")

    except Exception as e:
        logger.error(f"Ana döngü hatası: {e}")

    finally:
        # Tarayıcıları kapatma
        for username, bot in browser_instances.items():
            try:
                bot.close()
                logger.info(f"{username} için tarayıcı kapatıldı")
            except Exception as e:
                logger.error(f"{username} tarayıcısı kapatılırken hata: {e}")

if __name__ == "__main__":
    main()
