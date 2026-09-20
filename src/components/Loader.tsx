'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';

function LoaderContent() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setLoading(false), 850);

    return () => clearTimeout(t);
  }, []);

  return (
    <AnimatePresence>
      {loading && (
        <motion.div
          className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-ink"
          initial={{ opacity: 1 }}
          exit={{
            opacity: 0,
            transition: {
              duration: 0.45,
              ease: 'easeOut',
            },
          }}
        >
          <div className="absolute h-72 w-72 rounded-full bg-emerald-500/15 blur-3xl animate-blob" />

          <div className="absolute h-52 w-52 rounded-full bg-teal-400/10 blur-2xl animate-blob [animation-delay:-6s]" />

          <div className="relative flex items-center justify-center">
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                className="absolute rounded-full border border-emerald-400/40"
                style={{
                  width: 96,
                  height: 96,
                }}
                animate={{
                  scale: [1, 2.4],
                  opacity: [0.7, 0],
                }}
                transition={{
                  duration: 1.8,
                  repeat: Infinity,
                  delay: i * 0.55,
                  ease: 'easeOut',
                }}
              />
            ))}

            <motion.svg
              width="72"
              height="72"
              viewBox="0 0 24 24"
              fill="none"
              initial="hidden"
              animate="visible"
            >
              <motion.path
                d="M12 2l7 3v5c0 5-3.2 8.6-7 10-3.8-1.4-7-5-7-10V5l7-3z"
                stroke="#34d399"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                variants={{
                  hidden: {
                    pathLength: 0,
                  },
                  visible: {
                    pathLength: 1,
                  },
                }}
                transition={{
                  duration: 1.1,
                  ease: 'easeInOut',
                }}
              />

              <motion.path
                d="M8.5 12l2.4 2.4L15.7 9.6"
                stroke="#a7f3d0"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                variants={{
                  hidden: {
                    pathLength: 0,
                  },
                  visible: {
                    pathLength: 1,
                  },
                }}
                transition={{
                  duration: 0.7,
                  delay: 0.7,
                  ease: 'easeOut',
                }}
              />
            </motion.svg>
          </div>

          <div className="mt-8 flex gap-1 font-display text-lg font-bold tracking-[0.4em] text-emerald-100">
            {'GARDU'.split('').map((ch, i) => (
              <motion.span
                key={i}
                initial={{
                  opacity: 0,
                  y: 10,
                }}
                animate={{
                  opacity: 1,
                  y: 0,
                }}
                transition={{
                  delay: 0.15 * i,
                  duration: 0.4,
                }}
              >
                {ch}
              </motion.span>
            ))}
          </div>

          <motion.p
            className="mt-2 text-xs uppercase tracking-widest text-zinc-500"
            initial={{
              opacity: 0,
            }}
            animate={{
              opacity: 1,
            }}
            transition={{
              delay: 0.9,
            }}
          >
            Memuat peta keselamatan...
          </motion.p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default function PageLoader() {
  const pathname = usePathname();

  return <LoaderContent key={pathname} />;
}