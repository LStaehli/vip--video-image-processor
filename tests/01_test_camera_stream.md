 
# Test 1: Video streaming in browser
                                                                                                                                                                                                                                              
  How to test it now                                                                                                                                                                                                                                
                                                                                                                                                                                                                                                    
1. Start the server — run this in your terminal from the project root:                                                                                                                                                                            
                                                                                                                                                                                                                                                    
```bash
python -m uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload  
```                                                                                                                                                                       
                                                                                                                                                                                                                                                    
2. Grant camera permission — the first time, macOS will prompt to allow the terminal to access the camera. Click Allow in the system dialog (or go to System Settings → Privacy & Security → Camera and enable your terminal app).                
                                                                                                                                                                                                                                                    
3. Open the browser:                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                  
  http://localhost:8000                                                                                                                                                                                                                             
                                                                                                                                                                                                                                                  
  You should see:                                                                                                                                                                                                                                 
- Green dot + "Connected" in the header
- Your webcam feed in the canvas                                                                                                                                                                                                                  
- Live FPS counter updating every 2 seconds
- Feature checkboxes (all off for now — they'll do something in Phase 2+)                                                                                                                                                                         
                                                                                                                                                                                                                                                    
4. Optional — test MJPEG fallback:                                                                                                                                                                                                               
http://localhost:8000/stream.mjpeg                                                                                                                                                                                                                
                                                                                                                                                                                                                                                    
5. Optional — test runtime config (no restart needed):                                                                                                                                                                                            
### Drop to 5fps                                                                                                                                                                                                                                    
curl -X PUT http://localhost:8000/api/config \                                                                                                                                                                                                  
-H "Content-Type: application/json" \                                                                                                                                                                                                           
-d '{"target_fps": 5}'                                                                                                                                                                                                                          
                                                                                                                                                                                                                                                
### Back to 15fps, higher quality                                                                                                                                                                                                                   
curl -X PUT http://localhost:8000/api/config \                                                                                                                                                                                                    
-H "Content-Type: application/json" \                                                                                                                                                                                                         
-d '{"target_fps": 15, "jpeg_quality": 90}'                                                                                                                                                                                                     
                                                                                                                                                                                                                                              
Once you confirm the stream is showing in the browser, we're ready for Phase 2 (motion tracking).

--- 

# Test 2: Motion detector

```bash
 python -m uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload                                                                                                                                                                         
```

  Open http://localhost:8000 — you should see:                                                                                                                                                                                                      
                                                                                                                                                                                                                                                    
- Green contour drawn around any moving object/person                                                                                                                                                                                             
- Fading green trail of dots showing the path (older = dimmer, smaller)                                                                                                                                                                           
- Amber arrow pointing in the current direction of movement                                                                                                                                                                                       
                                                                                                                                                                                                                                                  
You can tune sensitivity live without restarting:                                                                                                                                                                                                 
                                                                                                                                                                                                                                              
### More sensitive (picks up smaller movements)                                                                                                                                                                                                     
curl -X PUT http://localhost:8000/api/config \                                                                                                                                                                                                    
-H "Content-Type: application/json" \                                                                                                                                                                                                         
-d '{"motion_mog2_threshold": 20, "motion_min_area": 400}'                                                                                                                                                                                      
                                                                                                                                                                                                                                              
### Less sensitive (only large movements)                                                                                                                                                                                                           
curl -X PUT http://localhost:8000/api/config \                                                                                                                                                                                                  
-H "Content-Type: application/json" \                                                                                                                                                                                                           
-d '{"motion_mog2_threshold": 60, "motion_min_area": 2000}'                                                                                                                                                                                   
                                                                                                                                                                                                                                                
Note: MOG2 needs ~3–5 seconds of still background to learn the scene before it starts detecting motion accurately — this is normal. 