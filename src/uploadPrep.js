// Client-side checks and photo shrinking before /api/pdf/analyze.
//
// Vercel rejects request bodies over ~4.5 MB, so every file in one upload
// shares a 4 MB budget (matches the backend's MAX_TOTAL_UPLOAD_BYTES). A
// single phone photo is often 3-8 MB, so photos are downscaled to JPEG here
// first — usually to well under 1 MB with no visible loss for reading notes.

export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;
export const MAX_UPLOAD_FILES = 5;

// What the file pickers offer. "image/*" (rather than a list of types) is
// what makes iOS/Android show "Photo Library" and "Take Photo", and lets
// iOS hand over HEIC photos as JPEG.
export const PICKER_ACCEPT = "application/pdf,.pdf,image/*";

const BACKEND_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"];
const IMAGE_EXTENSION = /\.(jpe?g|png|webp|heic|heif|gif|bmp|avif|tiff?)$/i;
const SHRINK_OVER_BYTES = 900 * 1024;
// [longest edge, JPEG quality] tried in order until the whole upload fits.
// Gemini tiles images at ~768px, so even the last step keeps print legible.
const SHRINK_STEPS = [
  [1600, 0.8],
  [1280, 0.72],
  [1024, 0.65],
];

export class UploadError extends Error {}

export function isPdf(file) {
  return file.type === "application/pdf" || /\.pdf$/i.test(file.name || "");
}

export function isImage(file) {
  return (file.type || "").startsWith("image/") || IMAGE_EXTENSION.test(file.name || "");
}

function isBackendImage(file) {
  return BACKEND_IMAGE_TYPES.includes((file.type || "").toLowerCase()) || /\.(jpe?g|png|webp|heic|heif)$/i.test(file.name || "");
}

export function formatMB(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Mirrors the backend's file_name summary so the UI shows the same label
// before and after the upload completes.
export function summarizeFileNames(names) {
  if (names.length <= 1) return names[0] || "";
  return `${names[0]} +${names.length - 1} more`;
}

async function decodeImage(file) {
  try {
    return await createImageBitmap(file);
  } catch {
    // Some browsers only decode certain formats through <img>.
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

// force: re-encode even a small, already-supported image (later steps,
// when the upload as a whole is still over budget).
async function shrinkImage(file, maxEdge, quality, force) {
  if (!force && file.size <= SHRINK_OVER_BYTES && isBackendImage(file)) return file;

  const image = await decodeImage(file);
  if (!image) {
    // e.g. HEIC in Chrome/Firefox: can't decode it here, but the backend
    // and Gemini accept it as-is (the size check below still applies).
    if (isBackendImage(file)) return file;
    throw new UploadError(`"${file.name}" couldn't be read as a photo. Try a JPEG or PNG instead.`);
  }

  const width = image.width;
  const height = image.height;
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; // transparent PNG screenshots become white, not black
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  image.close?.();

  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
  if (!blob) return isBackendImage(file) ? file : Promise.reject(new UploadError(`"${file.name}" couldn't be processed.`));
  if (blob.size >= file.size && isBackendImage(file)) return file;
  const base = (file.name || "photo").replace(/\.[^.]+$/, "");
  return new File([blob], `${base}.jpg`, { type: "image/jpeg", lastModified: Date.now() });
}

// Validates the selection and returns the files to send. Throws UploadError
// with a message written for the person, not the system.
export async function prepareUploadFiles(files) {
  if (files.length > MAX_UPLOAD_FILES) {
    throw new UploadError(
      `You can upload up to ${MAX_UPLOAD_FILES} files at a time — you picked ${files.length}.`
    );
  }

  for (const file of files) {
    if (!isPdf(file) && !isImage(file)) {
      throw new UploadError(`"${file.name}" isn't a PDF or photo. You can upload PDFs and JPEG, PNG, WEBP or HEIC photos.`);
    }
  }

  // Always re-encode from the originals, never from an earlier step's output.
  let prepared = files;
  for (const [index, [maxEdge, quality]] of SHRINK_STEPS.entries()) {
    prepared = [];
    for (const file of files) {
      prepared.push(isPdf(file) ? file : await shrinkImage(file, maxEdge, quality, index > 0));
    }
    const fits = prepared.reduce((sum, f) => sum + f.size, 0) <= MAX_UPLOAD_BYTES;
    if (fits || !files.some(isImage)) break;
  }

  const total = prepared.reduce((sum, f) => sum + f.size, 0);
  if (total > MAX_UPLOAD_BYTES) {
    if (prepared.length === 1 && isPdf(prepared[0])) {
      throw new UploadError(
        `"${prepared[0].name}" is ${formatMB(total)} — the limit is 4 MB. Try a smaller PDF, or upload the pages you need as photos.`
      );
    }
    throw new UploadError(
      `These files add up to ${formatMB(total)} (photos already shrunk) — the limit is 4 MB. Try fewer files or a smaller PDF.`
    );
  }
  return prepared;
}
