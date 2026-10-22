VANTEX SECURE CLOUDINARY GALLERY PATCH

1) Copy ai/cloudinary_gallery.py into ~/Desktop/VANTEX/ai/cloudinary_gallery.py
2) Copy frontend/CloudinaryGallery.tsx into ~/Desktop/VANTEX/apps/web/src/components/CloudinaryUploader/CloudinaryGallery.tsx
3) In ai/main.py, add this import after the existing imports:
   from ai.cloudinary_gallery import router as cloudinary_gallery_router
   Then, immediately after app = FastAPI(...), add:
   app.include_router(cloudinary_gallery_router)
   If app.add_middleware follows app creation, put include_router before or after middleware; either is fine.
4) In apps/web/src/components/Home/Home.tsx, add this import:
   import CloudinaryGallery from '../CloudinaryUploader/CloudinaryGallery';
   Inside the Home component, add state:
   const [showCloudinaryGallery, setShowCloudinaryGallery] = useState(false);
   Immediately after the existing <CloudinaryUploader /> JSX, add:
   <div style={{ display: 'flex', justifyContent: 'center', marginTop: 12 }}>
     <button type="button" className="qa-fix-button" onClick={() => setShowCloudinaryGallery(open => !open)}>
       {showCloudinaryGallery ? 'Hide cloud images' : 'View cloud images'}
     </button>
   </div>
   {showCloudinaryGallery && <CloudinaryGallery />}

5) Set these environment variables for the BACKEND process only (the gallery token should be a long random value):
   CLOUDINARY_CLOUD_NAME=your_cloud_name
   CLOUDINARY_API_KEY=your_api_key
   CLOUDINARY_API_SECRET=your_api_secret
   VANTEX_GALLERY_ACCESS_TOKEN=choose_a_long_random_private_token
   You can put them in the project-root .env if python-dotenv is installed (pip install python-dotenv), or export them in the terminal before starting FastAPI. Never put the API secret in frontend code, a VITE_* variable, or browser localStorage.

6) Restart FastAPI and refresh VANTEX. The gallery loads 30 images per page, supports refresh, client-side search among loaded pages, image preview, copy URL, and load more.

Backend route: GET /api/cloudinary/images?limit=30[&next_cursor=...]
The endpoint requires X-VANTEX-Gallery-Token, compared server-side with VANTEX_GALLERY_ACCESS_TOKEN, before it uses Cloudinary Admin API HTTP Basic authentication. Enter that token in the gallery UI; it is stored in this browser localStorage. This is a shared access gate, not per-user identity/authentication. For a public multi-user deployment, put the endpoint behind real user authentication/authorization before exposing account assets.
