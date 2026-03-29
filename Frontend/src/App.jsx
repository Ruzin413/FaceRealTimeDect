import React, { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
  const [activeTab, setActiveTab] = useState('detect');
  const [status, setStatus] = useState('');
  const [matches, setMatches] = useState([]);
  const [strangers, setStrangers] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState('');
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const wsRef = useRef(null);
  const matchIntervalRef = useRef(null);

  // Start Webcam and re-bind on tab switch
  useEffect(() => {
    let stream = null;
    const startCamera = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch (err) {
        setStatus(`Camera error: ${err.message}`);
      }
    };
    startCamera();

    return () => {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  // Re-bind stream when tab switches back to 'detect'
  useEffect(() => {
    if (activeTab === 'detect' && streamRef.current && videoRef.current) {
      const v = videoRef.current;
      v.srcObject = streamRef.current;
      v.onloadedmetadata = () => {
        v.play().catch(e => console.log("Cam playback prevented:", e));
      };
    }
  }, [activeTab]);

  // Handle Detection Lifecycle (WebSocket + Interval)
  useEffect(() => {
    if (activeTab !== 'detect') {
      if (activeTab === 'history') fetchStrangers();
      return;
    }

    let intervalId = null;
    let ws = null;
    let isComponentMounted = true;

    const connectWS = () => {
      ws = new WebSocket('ws://localhost:8000/match_frame');
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isComponentMounted) {
          ws.close();
          return;
        }
        console.log('WebSocket Connected');
        setStatus('Real-time detection active');

        intervalId = setInterval(() => {
          if (!videoRef.current || !canvasRef.current || ws.readyState !== WebSocket.OPEN) return;

          const video = videoRef.current;
          const canvas = canvasRef.current;
          const ctx = canvas.getContext('2d');

          canvas.width = video.videoWidth || 640;
          canvas.height = video.videoHeight || 480;
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

          canvas.toBlob((blob) => {
            if (blob && ws.readyState === WebSocket.OPEN) {
              ws.send(blob);
            }
          }, 'image/jpeg', 0.8);
        }, 200);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.matches) setMatches(data.matches);
        } catch (e) {
          console.error("Failed to parse matching results");
        }
      };

      ws.onclose = () => {
        if (isComponentMounted) {
          console.log('WebSocket Disconnected');
          setStatus('Monitoring paused');
          setMatches([]);
        }
      };

      ws.onerror = (e) => {
        if (isComponentMounted) {
          console.error("WebSocket error:", e);
        }
      };
    };

    connectWS();

    return () => {
      isComponentMounted = false;
      if (intervalId) clearInterval(intervalId);
      if (ws) {
        // Only close if it's not already closing or closed
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
      }
      wsRef.current = null;
    };
  }, [activeTab]);

  const fetchStrangers = async () => {
    try {
      const res = await fetch('http://localhost:5081/api/face/strangers');
      if (res.ok) {
        const data = await res.json();
        setStrangers(data);
      }
    } catch (err) {
      console.error("Failed to fetch strangers:", err);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this user?")) return;
    try {
      const res = await fetch(`http://localhost:5081/api/face/${id}`, { method: 'DELETE' });
      if (res.ok) {
        fetchStrangers();
      }
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const handleEdit = (user) => {
    setEditingId(user.id);
    setEditName(user.name);
  };

  const saveEdit = async (id) => {
    try {
      const res = await fetch(`http://localhost:5081/api/face/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editName })
      });
      if (res.ok) {
        setEditingId(null);
        fetchStrangers();
      }
    } catch (err) {
      console.error("Update failed:", err);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-900 text-white font-sans p-8 flex flex-col">
      <div className="max-w-5xl mx-auto w-full flex-grow">
        <h1 className="text-3xl font-black text-white/90 mb-8 text-center tracking-tight">
          Face Detect
        </h1>

        <div className="flex justify-center space-x-4 mb-8">
          <button
            onClick={() => setActiveTab('detect')}
            className={`px-8 py-3 rounded-full font-bold transition-all duration-300 ${activeTab === 'detect' ? 'bg-cyan-500 text-white shadow-[0_0_20px_rgba(6,182,212,0.6)] scale-105' : 'bg-neutral-800 text-neutral-400 hover:bg-neutral-700'}`}
          >
            Live Monitor
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`px-8 py-3 rounded-full font-bold transition-all duration-300 ${activeTab === 'history' ? 'bg-amber-500 text-white shadow-[0_0_20px_rgba(245,158,11,0.6)] scale-105' : 'bg-neutral-800 text-neutral-400 hover:bg-neutral-700'}`}
          >
            Detection History
          </button>
        </div>

        <div className="bg-neutral-800/80 backdrop-blur-xl rounded-3xl p-6 shadow-2xl border border-neutral-700/50 flex flex-col md:flex-row gap-8 relative overflow-hidden">

          {/* Left Column: Camera (Only in Detect Tab) */}
          {activeTab === 'detect' && (
            <div className="flex-1 relative rounded-2xl overflow-hidden bg-black aspect-video flex items-center justify-center border border-neutral-700 shadow-[inset_0_2px_20px_rgba(0,0,0,0.8)]">
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover"
              ></video>
              {/* Hidden canvas for extraction */}
              <canvas ref={canvasRef} className="hidden"></canvas>
              {/* Bounding box overlays */}
              {activeTab === 'detect' && matches.map((match, i) => {
                const [x1, y1, x2, y2] = match.bbox;
                const w = x2 - x1;
                const h = y2 - y1;
                // Render bounding box
                return (
                  <div key={i} className="absolute border-[3px] border-cyan-400 bg-cyan-400/10 box-border rounded-lg shadow-[0_0_15px_rgba(6,182,212,0.8)] transition-all duration-75 ease-linear pointer-events-none" style={{
                    left: `${(x1 / 640) * 100}%`,
                    top: `${(y1 / 480) * 100}%`,
                    width: `${(w / 640) * 100}%`,
                    height: `${(h / 480) * 100}%`
                  }}>
                    <div className="absolute -top-8 left-[-3px] bg-cyan-400 text-black px-3 py-1 text-sm font-extrabold whitespace-nowrap rounded-t-lg shadow-lg flex items-center space-x-2">
                      <span className="truncate max-w-[120px]">{match.name}</span>
                      {match.name !== 'Unknown' && (
                        <span className="text-cyan-900 drop-shadow-sm text-xs border border-cyan-900/50 rounded-full px-1.5 py-0.5 ml-1 bg-cyan-300 font-bold">
                          {(match.score * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          {/* Right Column: Dynamic Data */}
          <div className={`w-full ${activeTab === 'detect' ? 'md:w-1/3' : 'flex-1'} flex flex-col bg-neutral-900/50 p-6 rounded-2xl border border-neutral-800 shadow-inner overflow-hidden`}>
            {activeTab === 'detect' ? (
              <div className="space-y-6 flex flex-col items-center h-full">
                <div className="w-full">
                  <h3 className="text-sm font-bold text-cyan-400 uppercase tracking-widest ring-1 ring-cyan-400/30 px-3 py-1 rounded-full text-center">Monitoring</h3>
                </div>
                {/* Current Detection Feedback */}
                <div className="w-full mt-4 pt-4 border-t border-neutral-800 flex-grow overflow-hidden flex flex-col">
                  <div className="text-[10px] text-neutral-500 uppercase font-black tracking-widest mb-4 flex justify-between items-center px-1">
                    <span>Live Tracker</span>
                    <span className="flex items-center"><span className="w-1.5 h-1.5 bg-cyan-500 rounded-full mr-1.5 animate-pulse"></span> {matches.length} active</span>
                  </div>
                  <div className="space-y-3 overflow-y-auto pr-2 custom-scrollbar flex-grow">
                    {matches.length === 0 ? (
                      <div className="text-neutral-700 text-[10px] py-10 text-center border border-dashed border-neutral-800/50 rounded-xl uppercase font-bold tracking-widest">Scanning...</div>
                    ) : (
                      matches.map((m, i) => (
                        <div key={i} className="flex items-center space-x-3 bg-neutral-800/30 p-3 rounded-xl border border-neutral-700/30 hover:bg-neutral-800/50 transition-all">
                          <div className="w-8 h-8 rounded-full bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 font-bold text-xs ring-4 ring-cyan-500/5 uppercase">
                            {m.name.charAt(0)}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className={`${m.name.startsWith('Stranger') ? 'text-amber-400' : 'text-cyan-400'} text-xs font-black truncate uppercase`}>{m.name}</p>
                            <div className="flex items-center mt-0.5">
                                <div className="h-1 bg-neutral-800 rounded-full flex-1 overflow-hidden">
                                    <div className="h-full bg-cyan-500 rounded-full transition-all duration-500" style={{ width: `${(m.score * 100).toFixed(0)}%` }}></div>
                                </div>
                                <span className="text-[9px] text-neutral-500 ml-2 font-mono">{(m.score * 100).toFixed(0)}%</span>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col h-full">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-bold text-amber-500 uppercase tracking-widest">
                    History
                  </h3>
                  <button onClick={fetchStrangers} className="text-[10px] text-neutral-500 hover:text-white transition-colors uppercase font-bold">Refresh</button>
                </div>

                <div className="space-y-3 overflow-y-auto flex-grow pr-2 custom-scrollbar">
                  {strangers.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-40 border border-neutral-800 rounded-2xl">
                      <p className="text-neutral-700 text-[10px] uppercase font-bold">Empty</p>
                    </div>
                  ) : (
                    strangers.map((s, i) => (
                      <div key={i} className="group flex items-center space-x-3 bg-neutral-800/40 p-3 rounded-xl border border-neutral-700/30 hover:bg-neutral-800 hover:border-amber-500/30 transition-all duration-300">
                        <div className="relative w-12 h-12 flex-shrink-0">
                          <img
                            src={s.imageUrl}
                            className="w-full h-full rounded-lg object-cover ring-2 ring-neutral-700 group-hover:ring-amber-500/50 transition-all"
                            onError={(e) => { e.target.src = 'https://ui-avatars.com/api/?name=Face&background=222&color=aaa'; }}
                            alt={s.name}
                          />
                        </div>
                        <div className="flex-1 min-w-0">
                          {editingId === s.id ? (
                            <div className="flex space-x-2">
                              <input
                                value={editName}
                                onChange={(e) => setEditName(e.target.value)}
                                className="bg-neutral-900 border border-neutral-700 text-xs rounded px-2 py-1 w-full text-white"
                                autoFocus
                              />
                              <button onClick={() => saveEdit(s.id)} className="text-cyan-400 text-[10px] font-bold">Save</button>
                              <button onClick={() => setEditingId(null)} className="text-neutral-500 text-[10px]">Cancel</button>
                            </div>
                          ) : (
                            <>
                              <p className="text-sm font-bold text-white truncate group-hover:text-amber-400 transition-colors uppercase">{s.name}</p>
                              <p className="text-[10px] text-neutral-500 flex items-center">
                                <svg className="w-2.5 h-2.5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                                {new Date(s.createdAt).toLocaleTimeString()}
                              </p>
                            </>
                          )}
                        </div>
                        <div className="flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button onClick={() => handleEdit(s)} className="p-1.5 hover:bg-amber-500/20 rounded-lg text-amber-500 transition-colors">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
                          </button>
                          <button onClick={() => handleDelete(s.id)} className="p-1.5 hover:bg-red-500/20 rounded-lg text-red-500 transition-colors">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
export default App;
