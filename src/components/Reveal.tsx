'use client';

import { motion } from 'framer-motion';
import { ReactNode } from 'react';

export default function Reveal({
  children, delay = 0, y = 28, className,
}: {
  children: ReactNode; delay?: number; y?: number; className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y, filter: 'blur(6px)' }}
      whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.7, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}