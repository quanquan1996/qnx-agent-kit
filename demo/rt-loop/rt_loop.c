/* rt-loop: 1 kHz control loop demo for qnx-agent-kit.
 * Threads (SCHED_FIFO):
 *   control  prio 50  every 1 ms: lock shared state, compute PID step, unlock
 *   logger   prio 10  every 10 ms: lock shared state, snapshot it (~400 us),
 *                     and while still holding the lock wake the uploader
 *   uploader prio 30  woken by logger, sends the snapshot (busy 4 ms)
 * BUG (intentional): the shared lock is a POSIX semaphore. Semaphores have no
 * owner, so QNX cannot apply priority inheritance: when logger holds it,
 * uploader (30) preempts logger (10) mid-critical-section and control (50)
 * waits ~4 ms -> a missed deadline roughly every 10 ms (priority inversion).
 * FIX: use a pthread_mutex (QNX mutexes inherit priority by default).
 * Build with -DUSE_MUTEX to see the fix.
 * Metric: lock_waits_over_1ms / total_lock_wait_ms. Wake lateness (misses) is
 * also printed but is useless inside VirtualBox (timer jitter 40-50 ms).
 * Measured on QNX 8.0 x86_64 VBox VM, `on -C 0`, 5 s:
 *   semaphore: lock_waits_over_1ms=129 total_lock_wait_ms=524
 *   mutex:     lock_waits_over_1ms=5-6 total_lock_wait_ms=90 */
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define PERIOD_NS 1000000L
#define RUN_SECONDS 5
#define LATE_NS 1000000L /* a step later than 1 ms counts as a miss */

#ifdef USE_MUTEX
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
#define LOCK() pthread_mutex_lock(&lock)
#define UNLOCK() pthread_mutex_unlock(&lock)
#else
static sem_t lock;
#define LOCK() sem_wait(&lock)
#define UNLOCK() sem_post(&lock)
#endif

static volatile int running = 1;
static double setpoint = 1.0, value = 0.0, integ = 0.0, prev_err = 0.0;

static int64_t now_ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000000000LL + t.tv_nsec;
}
static void spin_ns(int64_t ns) { int64_t end = now_ns() + ns; while (now_ns() < end) {} }

static void *control(void *arg) {
    (void)arg;
    struct timespec next; clock_gettime(CLOCK_MONOTONIC, &next);
    long steps = 0, misses = 0, blocked = 0; int64_t worst = 0, worst_wait = 0, sum_wait = 0;
    int64_t stop = now_ns() + (int64_t)RUN_SECONDS * 1000000000LL;
    while (now_ns() < stop) {
        next.tv_nsec += PERIOD_NS;
        if (next.tv_nsec >= 1000000000L) { next.tv_nsec -= 1000000000L; next.tv_sec++; }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
        int64_t t0 = now_ns();
        LOCK();
        int64_t w = now_ns() - t0; /* time spent waiting for the lock */
        if (w > worst_wait) worst_wait = w;
        if (w > 1000000) blocked++;
        sum_wait += w;
        double err = setpoint - value;           /* PID step */
        integ += err * 0.001;
        double out = 2.0 * err + 0.5 * integ + 0.01 * (err - prev_err) / 0.001;
        prev_err = err; value += out * 0.001;
        UNLOCK();
        int64_t done = now_ns();
        int64_t late = done - ((int64_t)next.tv_sec * 1000000000LL + next.tv_nsec);
        if (late > worst) worst = late;
        if (late > LATE_NS) misses++;
        steps++;
    }
    running = 0;
    printf("RESULT lock=%s steps=%ld misses=%ld worst_late_us=%lld lock_waits_over_1ms=%ld worst_lock_wait_us=%lld total_lock_wait_ms=%lld\n",
#ifdef USE_MUTEX
           "mutex",
#else
           "semaphore",
#endif
           steps, misses, (long long)(worst / 1000), blocked, (long long)(worst_wait / 1000), (long long)(sum_wait / 1000000));
    return NULL;
}

static sem_t kick; /* logger -> uploader wake-up (a semaphore is right here) */

static void *logger(void *arg) {
    (void)arg;
    while (running) {
        LOCK();
        spin_ns(200000);            /* copy shared state into a log record */
        sem_post(&kick);            /* hand the record to the uploader... */
        spin_ns(200000);            /* ...while still finishing up under the lock */
        UNLOCK();
        struct timespec d = {0, 10000000}; nanosleep(&d, NULL);
    }
    sem_post(&kick);
    return NULL;
}

static void *uploader(void *arg) {
    (void)arg;
    while (running) { sem_wait(&kick); spin_ns(4000000); /* pretend network send */ }
    return NULL;
}

static pthread_t start(void *(*fn)(void *), int prio, const char *name) {
    pthread_attr_t a; struct sched_param sp = {.sched_priority = prio}; pthread_t t;
    pthread_attr_init(&a);
    pthread_attr_setinheritsched(&a, PTHREAD_EXPLICIT_SCHED);
    pthread_attr_setschedpolicy(&a, SCHED_FIFO);
    pthread_attr_setschedparam(&a, &sp);
    if (pthread_create(&t, &a, fn, NULL) != 0) { perror("pthread_create"); exit(1); }
    pthread_setname_np(t, name);
    return t;
}

int main(void) {
#if defined(USE_MUTEX) && !defined(__QNX__)
    { /* QNX mutexes inherit priority by default; Linux needs it explicitly */
      pthread_mutexattr_t ma; pthread_mutexattr_init(&ma);
      pthread_mutexattr_setprotocol(&ma, PTHREAD_PRIO_INHERIT); pthread_mutex_init(&lock, &ma); }
#endif
#ifndef USE_MUTEX
    sem_init(&lock, 0, 1);
#endif
    sem_init(&kick, 0, 0);
    /* single CPU makes the inversion deterministic; QNX: run with `on -C 1` or set runmask */
    pthread_t c = start(control, 50, "control");
    start(logger, 10, "logger");
    start(uploader, 30, "uploader");
    pthread_join(c, NULL);
    return 0;
}
