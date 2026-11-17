/* rt-loop: 1 kHz control loop (prio 50) sharing state with a logger (prio 10)
 * and an uploader (prio 30). Prints one RESULT line after 5 s. */
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

/* Shared-state lock: a priority-inheriting pthread mutex, NOT a sem_t.
 * A semaphore has no owner, so a low-prio holder (logger) could be preempted
 * by the mid-prio uploader while control (prio 50) waited: priority inversion. */
static pthread_mutex_t lock;
#define LOCK() pthread_mutex_lock(&lock)
#define UNLOCK() pthread_mutex_unlock(&lock)

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
    printf("RESULT steps=%ld misses=%ld worst_late_us=%lld lock_waits_over_1ms=%ld worst_lock_wait_us=%lld total_lock_wait_ms=%lld\n",
           steps, misses, (long long)(worst / 1000), blocked, (long long)(worst_wait / 1000), (long long)(sum_wait / 1000000));
    return NULL;
}

static sem_t kick;

static void *logger(void *arg) {
    (void)arg;
    while (running) {
        LOCK();
        spin_ns(200000);            /* copy shared state into a log record */
        spin_ns(200000);            /* finish up under the lock */
        UNLOCK();
        sem_post(&kick);            /* wake the uploader only after releasing the lock */
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
    pthread_mutexattr_t ma;
    pthread_mutexattr_init(&ma);
    pthread_mutexattr_setprotocol(&ma, PTHREAD_PRIO_INHERIT); /* explicit, though QNX default */
    pthread_mutex_init(&lock, &ma);
    sem_init(&kick, 0, 0);
    pthread_t c = start(control, 50, "control");
    start(logger, 10, "logger");
    start(uploader, 30, "uploader");
    pthread_join(c, NULL);
    return 0;
}
