import { usePluginData } from '@docusaurus/useGlobalData'

export interface ProcessedImageData {
  src: string
  processed: {
    thumbnail: string
    medium: string
    large: string
    original: string
  }
}

interface ImageManifest {
  [slug: string]: ProcessedImageData
}

export function useProcessedImage(
  imageSrc: string | undefined,
  postSlug: string,
): ProcessedImageData | null {
  let manifest: ImageManifest | undefined

  try {
    manifest = usePluginData('frontmatter-image-processor') as ImageManifest | undefined
  } catch (e) {
    // Plugin might not be active or data missing
    manifest = undefined
  }

  if (!imageSrc) {
    return null
  }

  // Extract slug from the post metadata or URL
  const processedData = manifest ? manifest[postSlug] : undefined

  if (processedData && processedData.src === imageSrc) {
    return processedData
  }

  // Fallback for images that haven't been processed
  return {
    src: imageSrc,
    processed: {
      thumbnail: imageSrc,
      medium: imageSrc,
      large: imageSrc,
      original: imageSrc,
    },
  }
}
