import React from 'react'
import FrameLayout from '@site/src/components/layout/FrameLayout'

interface RootProps {
  children: React.ReactNode
}

const Root: React.FC<RootProps> = ({ children }) => {
  return <FrameLayout>{children}</FrameLayout>
}

export default Root
