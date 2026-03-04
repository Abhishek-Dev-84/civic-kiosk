// ================= LANGUAGE MAP =================

const languageMap = {
    "en": "en-US",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "bn": "bn-IN",
    "or": "or-IN"   // ✅ Added Odia
};

// Detect current language from URL (/en/, /hi/, etc.)
function getCurrentLang() {
    const path = window.location.pathname.split('/');
    const langCode = path[1];
    return languageMap[langCode] || "en-US";
}

function getCurrentLangCode() {
    const path = window.location.pathname.split('/');
    return path[1] || "en";
}

// ================= TEXT TO SPEECH =================

function speak(text) {
    if (!('speechSynthesis' in window)) {
        alert("Speech not supported");
        return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = getCurrentLang();
    utterance.rate = 1;
    utterance.pitch = 1;

    speechSynthesis.cancel();
    speechSynthesis.speak(utterance);
}

// ================= SPEECH TO TEXT =================

function startListening(callback) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        alert("Speech recognition not supported in this browser.");
        return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = getCurrentLang();
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = function(event) {
        const transcript = event.results[0][0].transcript.toLowerCase();
        console.log("Heard:", transcript);
        if (callback) callback(transcript);
    };

    recognition.onerror = function(event) {
        console.error("Speech error:", event.error);
        speak("Sorry, I did not understand.");
    };

    recognition.start();
}

// ================= UNIVERSAL VOICE NAVIGATION =================

function startVoiceAssistant() {

    speak("Listening");

    startListening(function(command) {

        const currentLang = getCurrentLangCode();

        // BACK
        if (command.includes("back")) {
            window.history.back();
            return;
        }

        // HOME (language safe)
        if (command.includes("home")) {
            window.location.href = "/" + currentLang + "/";
            return;
        }

        // SMART BUTTON MATCHING
        let clickableElements = document.querySelectorAll("button, a, .menu-card, .lang-btn");

        for (let el of clickableElements) {

            let text = el.innerText.trim().toLowerCase();

            if (!text) continue;

            // Check partial word match
            let words = text.split(" ");

            for (let word of words) {
                if (word.length > 2 && command.includes(word)) {
                    el.click();
                    return;
                }
            }
        }

        speak("Command not recognized");
    });
}