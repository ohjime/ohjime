import React, { PropsWithChildren } from 'react'

const ImageWrapper = ({ children }: PropsWithChildren<object>): React.JSX.Element => {
  return (
    <div
      style={{
        display: 'flex',
        gap: '1rem',
        paddingBottom: '1rem',
        maxWidth: '100%',
        width: '100%',
      }}
    >
      {React.Children.map(children, (child) => (
        <div style={{ flex: 1, minWidth: 0 }}>
          {React.isValidElement(child)
            ? React.cloneElement(child as React.ReactElement<any>, {
              style: { width: '100%', height: 'auto', display: 'block', ...(child.props as any).style },
            })
            : child}
        </div>
      ))}
    </div>
  )
}

export default ImageWrapper
