(() => {
  "use strict";

  // The token stays in the URL fragment: fragments are never sent in HTTP
  // requests or referrer headers, and keeping it makes a manual reload safe.
  const token = location.hash.slice(1);
  const isSettings = location.pathname === "/settings";
  const restView = document.getElementById("restView");
  const settingsView = document.getElementById("settingsView");
  restView.hidden = isSettings;
  settingsView.hidden = !isSettings;

  let currentState = null;
  let audioContext = null;
  let master = null;
  let musicBus = null;
  let scheduler = null;
  let chordIndex = 0;
  let customAudio = null;
  let customSource = null;
  let playlistIndex = 0;
  let radioAudio = null;
  let radioFadeTimer = null;
  let radioAttempts = new Set();
  let lockedRadioStationId = null;
  let controlsTimer = null;
  let finishing = false;

  const api = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    headers.set("X-Codex-Rest-Token", token);
    if (options.body && typeof options.body === "string") headers.set("Content-Type", "application/json");
    const response = await fetch(path, {...options, headers});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Request failed");
    return data;
  };

  const saveSettings = async changes => {
    const updated = await api("/api/settings", {method: "POST", body: JSON.stringify(changes)});
    if (currentState) currentState.settings = updated;
    return updated;
  };

  const ensureAudio = () => {
    if (audioContext) return audioContext;
    audioContext = new AudioContext();
    master = audioContext.createGain();
    musicBus = audioContext.createGain();
    const compressor = audioContext.createDynamicsCompressor();
    compressor.threshold.value = -24;
    compressor.knee.value = 20;
    compressor.ratio.value = 4;
    musicBus.connect(compressor).connect(master).connect(audioContext.destination);
    return audioContext;
  };

  const fadeMusic = (enabled, seconds = .45) => {
    if (!currentState) return;
    const target = enabled ? currentState.settings.music_volume : 0;
    if (musicBus) {
      const now = audioContext.currentTime;
      musicBus.gain.cancelScheduledValues(now);
      musicBus.gain.setValueAtTime(Math.max(.0001, musicBus.gain.value), now);
      musicBus.gain.exponentialRampToValueAtTime(Math.max(.0001, target), now + seconds);
    }
    if (radioAudio) {
      clearInterval(radioFadeTimer);
      const audio = radioAudio;
      const start = audio.volume;
      const startedAt = performance.now();
      radioFadeTimer = setInterval(() => {
        if (radioAudio !== audio) return clearInterval(radioFadeTimer);
        const progress = Math.min(1, (performance.now() - startedAt) / (seconds * 1000));
        audio.volume = Math.max(0, Math.min(1, start + (target - start) * progress));
        if (progress === 1) clearInterval(radioFadeTimer);
      }, 40);
    }
  };

  const softTone = (frequency, start, duration, amount, type = "sine") => {
    const osc = audioContext.createOscillator();
    const gain = audioContext.createGain();
    const filter = audioContext.createBiquadFilter();
    osc.type = type;
    osc.frequency.value = frequency;
    filter.type = "lowpass";
    filter.frequency.value = 1500;
    gain.gain.setValueAtTime(.0001, start);
    gain.gain.exponentialRampToValueAtTime(amount, start + .6);
    gain.gain.exponentialRampToValueAtTime(.0001, start + duration);
    osc.connect(filter).connect(gain).connect(musicBus);
    osc.start(start);
    osc.stop(start + duration + .05);
  };

  const scheduleChord = () => {
    if (!audioContext || !currentState?.settings.music_enabled || currentState.settings.music_source !== "builtin") return;
    const progression = [
      [196.00, 246.94, 293.66, 369.99],
      [174.61, 220.00, 261.63, 329.63],
      [146.83, 196.00, 246.94, 293.66],
      [164.81, 207.65, 246.94, 311.13],
    ];
    const now = audioContext.currentTime + .08;
    const chord = progression[chordIndex++ % progression.length];
    chord.forEach((note, index) => softTone(note, now + index * .07, 7.7, .022, index % 2 ? "sine" : "triangle"));
    softTone(chord[2] * 2, now + 1.15, 2.1, .014, "sine");
    softTone(chord[1] * 2, now + 3.1, 2.5, .011, "sine");
  };

  const stopCustom = () => {
    if (customAudio) {
      customAudio.pause();
      customAudio.removeAttribute("src");
      customAudio.load();
    }
    customAudio = null;
    customSource = null;
  };

  const stopRadio = () => {
    clearInterval(radioFadeTimer);
    radioFadeTimer = null;
    const audio = radioAudio;
    radioAudio = null;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
  };

  const radioStatus = message => {
    const element = document.getElementById("radioPlaybackStatus");
    if (element) element.textContent = message;
  };

  const rememberLockedStation = stationId => {
    lockedRadioStationId = stationId;
    try { sessionStorage.setItem("codex-rest-radio-station", stationId); } catch (_) {}
  };

  const lockedStation = stations => {
    if (lockedRadioStationId && stations.some(station => station.id === lockedRadioStationId)) {
      return lockedRadioStationId;
    }
    lockedRadioStationId = null;
    try {
      const saved = sessionStorage.getItem("codex-rest-radio-station");
      if (stations.some(station => station.id === saved)) lockedRadioStationId = saved;
    } catch (_) {}
    if (!lockedRadioStationId && stations.length) {
      rememberLockedStation(stations[Math.floor(Math.random() * stations.length)].id);
    }
    return lockedRadioStationId;
  };

  const syncLockedRadioName = stationId => {
    const station = currentState?.settings.radio_stations.find(item => item.id === stationId);
    const element = document.getElementById("lockedRadioName");
    if (element) element.textContent = station?.name || "選局できません";
  };

  const playRadio = stationId => {
    const settings = currentState?.settings;
    const stations = settings?.radio_stations || [];
    const station = stations.find(item => item.id === stationId);
    if (!station) return fallbackFromRadio();
    stopRadio();
    radioAttempts.add(station.id);
    if (settings.radio_mode === "random_locked") {
      rememberLockedStation(station.id);
      syncLockedRadioName(station.id);
    }
    const audio = new Audio(station.url);
    radioAudio = audio;
    audio.preload = "none";
    audio.volume = Math.max(0, Math.min(1, settings.music_volume));
    radioStatus(`${station.name} に接続中…`);
    let connectionTimer = null;
    audio.addEventListener("playing", () => {
      clearTimeout(connectionTimer);
      if (radioAudio === audio) radioStatus(`${station.name} を再生中`);
    });
    let failed = false;
    const tryAnother = () => {
      if (failed || radioAudio !== audio) return;
      failed = true;
      clearTimeout(connectionTimer);
      const remaining = stations.filter(item => !radioAttempts.has(item.id));
      if (!remaining.length) return fallbackFromRadio();
      const next = settings.radio_mode === "random_locked"
        ? remaining[Math.floor(Math.random() * remaining.length)]
        : remaining[0];
      radioStatus(`${station.name} を再生できないため別の局を試します…`);
      playRadio(next.id);
    };
    audio.addEventListener("error", tryAnother, {once: true});
    connectionTimer = setTimeout(tryAnother, 15000);
    audio.play().catch(error => {
      if (error?.name === "NotAllowedError") {
        clearTimeout(connectionTimer);
        radioStatus("自動再生が制限されました。音楽をOFFからONにして再開できます。");
      } else {
        tryAnother();
      }
    });
  };

  const fallbackFromRadio = () => {
    stopRadio();
    radioStatus("再生できるラジオ局がないため、内蔵曲へ切り替えます。");
    saveSettings({music_source: "builtin"}).then(startMusic).catch(() => {});
  };

  const playCustom = () => {
    const tracks = currentState?.settings.tracks || [];
    if (!tracks.length) {
      saveSettings({music_source: "builtin"}).then(() => startMusic());
      return;
    }
    stopCustom();
    if (currentState.settings.playlist_order === "shuffle") playlistIndex = Math.floor(Math.random() * tracks.length);
    else playlistIndex %= tracks.length;
    const track = tracks[playlistIndex];
    customAudio = new Audio(`/media/${encodeURIComponent(track.id)}?t=${encodeURIComponent(token)}`);
    customAudio.preload = "auto";
    customSource = audioContext.createMediaElementSource(customAudio);
    customSource.connect(musicBus);
    customAudio.addEventListener("ended", () => { playlistIndex += 1; playCustom(); }, {once: true});
    customAudio.addEventListener("error", () => { playlistIndex += 1; if (playlistIndex < tracks.length * 2) playCustom(); else saveSettings({music_source: "builtin"}).then(startMusic); }, {once: true});
    customAudio.play().catch(() => {});
  };

  const startMusic = () => {
    if (!currentState?.settings.music_enabled || isSettings) return;
    ensureAudio().resume().catch(() => {});
    clearInterval(scheduler);
    scheduler = null;
    stopCustom();
    stopRadio();
    radioAttempts = new Set();
    if (currentState.settings.music_source === "playlist" && currentState.settings.tracks.length) {
      musicBus.gain.value = Math.max(.0001, currentState.settings.music_volume);
      playCustom();
    } else if (currentState.settings.music_source === "radio") {
      musicBus.gain.value = .0001;
      const stations = currentState.settings.radio_stations;
      if (!stations.length) return fallbackFromRadio();
      const stationId = currentState.settings.radio_mode === "random_locked"
        ? lockedStation(stations)
        : currentState.settings.radio_station_id || stations[0].id;
      playRadio(stationId);
    } else {
      musicBus.gain.value = Math.max(.0001, currentState.settings.music_volume);
      scheduleChord();
      scheduler = setInterval(scheduleChord, 7600);
    }
  };

  const stopMusic = (seconds = .35) => {
    if (musicBus) fadeMusic(false, seconds);
    setTimeout(() => {
      clearInterval(scheduler);
      scheduler = null;
      stopCustom();
      stopRadio();
    }, seconds * 1000 + 60);
  };

  const setToggle = (element, label, value, icon) => {
    element.setAttribute("aria-pressed", String(value));
    element.setAttribute("aria-label", `${label} ${value ? "ON" : "OFF"}`);
    element.innerHTML = `<span aria-hidden="true">${icon}</span><span>${label}</span><strong>${value ? "ON" : "OFF"}</strong>`;
  };

  const syncRestControls = settings => {
    setToggle(document.getElementById("musicToggle"), "音楽", settings.music_enabled, "♫");
    setToggle(document.getElementById("chimeToggle"), "完了通知音", settings.completion_sound_enabled, "♢");
    document.getElementById("musicVolume").value = settings.music_volume;
    document.getElementById("chimeVolume").value = settings.completion_volume;
  };

  const stationOptions = (select, stations, selectedId) => {
    const signature = JSON.stringify(stations.map(station => [station.id, station.name]));
    if (select.dataset.signature !== signature) {
      select.replaceChildren(...stations.map(station => {
        const option = document.createElement("option");
        option.value = station.id;
        option.textContent = station.name;
        return option;
      }));
      select.dataset.signature = signature;
    }
    if (stations.some(station => station.id === selectedId)) select.value = selectedId;
  };

  const syncRadioControls = settings => {
    const panel = document.getElementById("radioControls");
    const stations = settings.radio_stations || [];
    panel.hidden = settings.music_source !== "radio" || !stations.length;
    if (panel.hidden) return;
    const selectable = settings.radio_mode === "selectable";
    document.getElementById("selectableRadioControl").hidden = !selectable;
    document.getElementById("lockedRadioControl").hidden = selectable;
    if (selectable) {
      const selectedId = settings.radio_station_id || stations[0].id;
      stationOptions(document.getElementById("radioStationSelect"), stations, selectedId);
    } else {
      syncLockedRadioName(lockedStation(stations));
    }
  };

  const playbackSignature = settings => JSON.stringify({
    enabled: settings.music_enabled,
    source: settings.music_source,
    order: settings.playlist_order,
    tracks: settings.tracks.map(track => [track.id, track.file]),
    radioMode: settings.radio_mode,
    radioStationId: settings.radio_station_id,
    stations: settings.radio_stations.map(station => [station.id, station.url]),
  });

  const syncTaskState = state => {
    const summary = document.getElementById("taskStateSummary");
    const resetButton = document.getElementById("resetTaskState");
    if (!summary || !resetButton) return;
    if (state.active_count === 0) {
      summary.textContent = "現在、残っているタスクはありません。";
      resetButton.disabled = true;
    } else {
      const paused = state.paused_count ? `（承認待ち ${state.paused_count} 件）` : "";
      summary.textContent = `稼働中と認識しているタスク: ${state.active_count} 件${paused}`;
      resetButton.disabled = false;
    }
  };

  const finish = () => {
    if (finishing) return;
    finishing = true;
    stopMusic(1.45);
    document.body.classList.add("finishing");
  };

  const poll = async () => {
    try {
      const state = await api("/api/state");
      const previous = currentState;
      currentState = state;
      if (!isSettings) {
        syncRestControls(state.settings);
        syncRadioControls(state.settings);
        if (previous && previous.settings.music_volume !== state.settings.music_volume) {
          if (radioAudio) radioAudio.volume = state.settings.music_volume;
          else if (musicBus && state.settings.music_enabled) musicBus.gain.value = Math.max(.0001, state.settings.music_volume);
        }
        if (!previous && state.settings.music_enabled) startMusic();
        else if (previous && playbackSignature(previous.settings) !== playbackSignature(state.settings)) {
          if (state.settings.music_enabled) startMusic(); else stopMusic();
        }
        if (state.phase === "finishing") finish();
        if (state.phase === "active" && finishing) location.reload();
      } else {
        renderSettings(state.settings);
        syncTaskState(state);
      }
    } catch (_) {}
  };

  if (!isSettings) {
    document.getElementById("musicToggle").addEventListener("click", async () => {
      const enabled = !currentState.settings.music_enabled;
      await saveSettings({music_enabled: enabled});
      syncRestControls(currentState.settings);
      if (enabled) startMusic(); else stopMusic();
    });
    document.getElementById("chimeToggle").addEventListener("click", async () => {
      await saveSettings({completion_sound_enabled: !currentState.settings.completion_sound_enabled});
      syncRestControls(currentState.settings);
    });
    document.getElementById("musicVolume").addEventListener("input", event => {
      currentState.settings.music_volume = Number(event.target.value);
      if (musicBus && currentState.settings.music_enabled && currentState.settings.music_source !== "radio") {
        musicBus.gain.value = Math.max(.0001, currentState.settings.music_volume);
      }
      if (radioAudio && currentState.settings.music_enabled) radioAudio.volume = currentState.settings.music_volume;
    });
    document.getElementById("musicVolume").addEventListener("change", event => saveSettings({music_volume: Number(event.target.value)}));
    document.getElementById("chimeVolume").addEventListener("change", event => saveSettings({completion_volume: Number(event.target.value)}));
    document.getElementById("radioStationSelect").addEventListener("change", async event => {
      await saveSettings({radio_station_id: event.target.value});
      radioAttempts = new Set();
      if (currentState.settings.music_enabled) playRadio(event.target.value);
    });
    document.getElementById("closeRest").addEventListener("click", () => api("/api/close", {method: "POST", body: "{}"}));
    document.addEventListener("mousemove", () => {
      document.body.classList.add("controls-visible");
      clearTimeout(controlsTimer);
      controlsTimer = setTimeout(() => document.body.classList.remove("controls-visible"), 2600);
    });
    setInterval(() => {
      if (!currentState?.started_at) return;
      const seconds = Math.max(0, Math.floor(Date.now() / 1000 - currentState.started_at));
      document.getElementById("elapsed").textContent = `${String(Math.floor(seconds / 60)).padStart(2,"0")}:${String(seconds % 60).padStart(2,"0")}`;
    }, 1000);
  }

  let settingsRendered = false;
  const renderSettings = settings => {
    if (settingsRendered) return;
    settingsRendered = true;
    const musicButton = document.getElementById("settingsMusicToggle");
    const chimeButton = document.getElementById("settingsChimeToggle");
    setToggle(musicButton, "音楽", settings.music_enabled, "♫");
    setToggle(chimeButton, "完了通知音", settings.completion_sound_enabled, "♢");
    document.getElementById("settingsMusicVolume").value = settings.music_volume;
    document.getElementById("settingsChimeVolume").value = settings.completion_volume;
    const sourceInput = document.querySelector(`input[name="musicSource"][value="${settings.music_source}"]`);
    if (sourceInput) sourceInput.checked = true;
    document.getElementById("playlistOrder").value = settings.playlist_order;
    document.getElementById("playlistSettings").hidden = settings.music_source !== "playlist";
    document.getElementById("radioSettings").hidden = settings.music_source !== "radio";
    document.getElementById("radioMode").value = settings.radio_mode;
    document.getElementById("defaultRadioRow").hidden = settings.radio_mode !== "selectable";
    const stationSelect = document.getElementById("settingsRadioStation");
    stationOptions(stationSelect, settings.radio_stations, settings.radio_station_id);
    stationSelect.disabled = !settings.radio_stations.length;
    renderTrackList(settings.tracks);
    renderRadioStationList(settings.radio_stations);
  };

  const renderTrackList = tracks => {
    const list = document.getElementById("trackList");
    list.replaceChildren(...tracks.map(track => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = track.name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "削除";
      remove.addEventListener("click", async () => {
        await api(`/api/tracks/${encodeURIComponent(track.id)}`, {method: "DELETE"});
        settingsRendered = false;
        await poll();
      });
      item.append(name, remove);
      return item;
    }));
  };

  const renderRadioStationList = stations => {
    const list = document.getElementById("radioStationList");
    list.replaceChildren(...stations.map(station => {
      const item = document.createElement("li");
      const details = document.createElement("span");
      const name = document.createElement("strong");
      const url = document.createElement("small");
      name.textContent = station.name;
      url.textContent = station.url;
      details.className = "station-details";
      details.append(name, url);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "削除";
      remove.setAttribute("aria-label", `${station.name} を削除`);
      remove.addEventListener("click", async () => {
        await api(`/api/radio-stations/${encodeURIComponent(station.id)}`, {method: "DELETE"});
        settingsRendered = false;
        await poll();
      });
      item.append(details, remove);
      return item;
    }));
  };

  if (isSettings) {
    document.getElementById("settingsMusicToggle").addEventListener("click", async () => { await saveSettings({music_enabled: !currentState.settings.music_enabled}); settingsRendered = false; poll(); });
    document.getElementById("settingsChimeToggle").addEventListener("click", async () => { await saveSettings({completion_sound_enabled: !currentState.settings.completion_sound_enabled}); settingsRendered = false; poll(); });
    document.getElementById("settingsMusicVolume").addEventListener("change", event => saveSettings({music_volume: Number(event.target.value)}));
    document.getElementById("settingsChimeVolume").addEventListener("change", event => saveSettings({completion_volume: Number(event.target.value)}));
    document.querySelectorAll('input[name="musicSource"]').forEach(input => input.addEventListener("change", async event => {
      await saveSettings({music_source: event.target.value});
      settingsRendered = false;
      await poll();
    }));
    document.getElementById("playlistOrder").addEventListener("change", event => saveSettings({playlist_order: event.target.value}));
    document.getElementById("radioMode").addEventListener("change", async event => {
      await saveSettings({radio_mode: event.target.value});
      settingsRendered = false;
      await poll();
    });
    document.getElementById("settingsRadioStation").addEventListener("change", event => saveSettings({radio_station_id: event.target.value}));
    document.getElementById("radioStationForm").addEventListener("submit", async event => {
      event.preventDefault();
      const status = document.getElementById("radioStationStatus");
      const name = document.getElementById("radioStationName");
      const url = document.getElementById("radioStationUrl");
      status.textContent = "ラジオ局を追加しています…";
      try {
        await api("/api/radio-stations", {
          method: "POST",
          body: JSON.stringify({name: name.value, url: url.value}),
        });
        name.value = "";
        url.value = "";
        status.textContent = "ラジオ局を追加しました。";
        settingsRendered = false;
        await poll();
      } catch (error) {
        status.textContent = `追加できませんでした: ${error.message}`;
      }
    });
    document.getElementById("resetTaskState").addEventListener("click", async event => {
      const activeCount = currentState?.active_count || 0;
      if (!activeCount) return;
      if (!window.confirm(
        `Codex Restが記憶している ${activeCount} 件のタスクを解除しますか？\n設定と音源は削除されません。`
      )) return;
      const status = document.getElementById("resetStatus");
      event.currentTarget.disabled = true;
      status.textContent = "状態をリセットしています…";
      try {
        const result = await api("/api/reset", {method: "POST", body: "{}"});
        currentState = result.state;
        syncTaskState(currentState);
        status.textContent = `${result.cleared_count} 件を解除しました。次のプロンプトから通常どおり動作します。`;
      } catch (error) {
        event.currentTarget.disabled = false;
        status.textContent = `リセットできませんでした: ${error.message}`;
      }
    });
    document.getElementById("trackUpload").addEventListener("change", async event => {
      const status = document.getElementById("uploadStatus");
      for (const file of event.target.files) {
        status.textContent = `${file.name} を取り込んでいます…`;
        try {
          await api("/api/tracks", {method: "POST", headers: {"X-File-Name": encodeURIComponent(file.name)}, body: file});
        } catch (error) { status.textContent = `${file.name}: ${error.message}`; }
      }
      status.textContent = "取り込みが完了しました。";
      event.target.value = "";
      settingsRendered = false;
      await poll();
    });
  }

  poll();
  setInterval(poll, 500);
})();
