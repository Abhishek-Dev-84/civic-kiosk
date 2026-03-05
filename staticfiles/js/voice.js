// ================= LANGUAGE MAP =================

const languageMap = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "bn": "bn-IN",
    "or": "or-IN"
};

function getCurrentLang() {
    const path = window.location.pathname.split('/');
    return languageMap[path[1]] || "en-IN";
}

function getCurrentLangCode() {
    const path = window.location.pathname.split('/');
    return path[1] || "en";
}

// ================= TEXT TO SPEECH =================

function speak(text) {
    if (!('speechSynthesis' in window)) return;

    speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = getCurrentLang();
    utterance.rate = 1;
    speechSynthesis.speak(utterance);
}

// ================= SPEECH RECOGNITION ENGINE =================

const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

let recognition = SpeechRecognition ? new SpeechRecognition() : null;

if (recognition) {
    recognition.lang = getCurrentLang();
    recognition.continuous = true;  // 🔥 Continuous kiosk mode
    recognition.interimResults = false;
}

// ================= AUTO READ PAGE =================

function autoReadPage() {
    let heading = document.querySelector("h1");
    if (heading) {
        speak(heading.innerText);
    }
}

// ================= UNIVERSAL COMMAND HANDLER =================

function handleCommand(command) {

    command = command.toLowerCase();
    console.log("Heard:", command);

    const langCode = getCurrentLangCode();

    // BACK
    if (command.includes("back") || command.includes("वापस") || command.includes("ପଛକୁ")) {
        window.history.back();
        return;
    }

    // HOME
    if (command.includes("home") || command.includes("होम") || command.includes("ଘର")) {
        window.location.href = "/" + langCode + "/";
        return;
    }

    // SUBMIT
    if (command.includes("submit") || command.includes("जमा") || command.includes("ଦାଖଲ")) {
        let submitBtn = document.querySelector("button[type='submit'], .submit-btn");
        if (submitBtn) submitBtn.click();
        return;
    }

    // DOWNLOAD
    if (command.includes("download") || command.includes("डाउनलोड") || command.includes("ଡାଉନଲୋଡ")) {
        let downloadBtn = document.querySelector(".download-btn");
        if (downloadBtn) downloadBtn.click();
        return;
    }

    // FILL NUMBER INPUT (Consumer No, Load, etc.)
    let numberMatch = command.match(/\d+(\.\d+)?/);
    if (numberMatch) {
        let inputs = document.querySelectorAll("input:not([type='hidden'])");
        for (let input of inputs) {
            if (input.offsetParent !== null) {
                input.value = numberMatch[0];
                speak("Value entered");
                return;
            }
        }
    }

    // SMART CLICK BY TEXT MATCH
    let clickable = document.querySelectorAll("button, a, .menu-card, .lang-btn");

    for (let el of clickable) {

        let text = el.innerText.trim().toLowerCase();
        if (!text) continue;

        let words = text.split(" ");

        for (let word of words) {
            if (word.length > 2 && command.includes(word)) {
                el.click();
                return;
            }
        }
    }

    speak("Command not recognized");
}

// ================= START LISTENING =================

function startVoiceEngine() {
    if (!recognition) return;

    recognition.lang = getCurrentLang();
    recognition.start();
}

if (recognition) {

    recognition.onresult = function (event) {
        let transcript =
            event.results[event.results.length - 1][0].transcript;
        handleCommand(transcript);
    };

    recognition.onerror = function () {
        recognition.stop();
        startVoiceEngine();
    };

    recognition.onend = function () {
        startVoiceEngine(); // 🔥 Auto restart (continuous kiosk)
    };
}

// ================= AUTO MIC BUTTON =================

function createMicButton() {

    const mic = document.createElement("div");
    mic.innerHTML = "🎤";
    mic.style.position = "fixed";
    mic.style.top = "80px";
    mic.style.right = "20px";
    mic.style.width = "60px";
    mic.style.height = "60px";
    mic.style.borderRadius = "50%";
    mic.style.background = "#ff9933";
    mic.style.display = "flex";
    mic.style.alignItems = "center";
    mic.style.justifyContent = "center";
    mic.style.fontSize = "28px";
    mic.style.cursor = "pointer";
    mic.style.zIndex = "9999";
    mic.style.boxShadow = "0 5px 15px rgba(0,0,0,0.3)";

    mic.onclick = function () {
        speak("Voice assistant activated");
        startVoiceEngine();
    };

    document.body.appendChild(mic);
}

// ================= INIT =================

window.addEventListener("load", function () {

    createMicButton();
    autoReadPage();

    // 🔥 Start automatically (full kiosk mode)
    startVoiceEngine();
});