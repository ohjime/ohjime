import React from 'react'
import Layout from '@theme/Layout'
import Image from '@theme/IdealImage'
import { FaGithub, FaLinkedinIn, FaStackOverflow, FaTwitter, FaAt } from 'react-icons/fa6'
import Card from '@site/src/components/Home/Card/Card'

const Index = (): JSX.Element => {
  return (
    <Layout title="About me" description="About me">
      <div className="flex flex-col md:flex-row gap-8 p-8 lg:gap-12 lg:p-12">
        <div className="flex flex-col w-auto md:w-88 shrink-0 grow-0 self-center md:self-start ">
          <h1 className="text-2xl">Hi. Im Ozzy.</h1>

          <p>
            Welcome to my portfolio page. I will periodically update this site with blogs on my latest projects, amateur photography/artwork, and my lecture notes! Enjoy!
          </p>

          <div style={{ marginBottom: '0em' }}>
            <Image
              className="[&:not(dialog_&)_img]:rounded-lg"
              img={require('@site/src/assets/ozzy.jpg')}
            />
          </div>

          <p className="text-left -mt-9">
            <hr />
            <b className="font-bold text-sm">Figure 1:</b> Ozzy Fishes.
            "<i className="text-sm">A wise man once told me 'If you teach a man to fish...', so He taught me to fish. I still have no fish. Getting Hungry...</i>"
          </p>

          <div className="flex justify-center items-center mt-4 gap-4 [&_a]:text-[#989586] [&_a:hover]:text-pink-dark [&_a:hover]:animate-pulse">
            <a target="_blank" rel="noreferrer" href="mailto:jimeo@mymacewan.ca">
              <FaAt size={32} />
            </a>
            <a target="_blank" rel="noreferrer" href="https://www.linkedin.com/in/osmanjime/">
              <FaLinkedinIn size={32} />
            </a>
          </div>
        </div>

        <div className="flex grow flex-row flex-wrap gap-8">

          <Card title="Education 🎓">
            <Card.Item>B.Sc. Dual Major - CS, Mathematics
              <div className="text-md font-bold">MacEwan University</div>
              <div className="text-sm">Sep 2023 - Current</div>
            </Card.Item>
            <hr />
            <Card.Item>B.Sc. Physics
              <div className="text-md font-bold">University of Calgary</div>
              <div className="text-sm">Graduated Jun 2023</div>
            </Card.Item>
          </Card>

          <Card title="Quench">
            <Card.Item>Product Engineer
              <div className="text-md font-bold">Edmonton, AB</div>
              <div className="text-sm">Apr 2025 - Current</div>
            </Card.Item>
            <hr />
            <Card.Item>
              <div className="text-xs">Designing and Manufacturing a new Quench Prototype with Dyna and Andy! Day to Day includes: Firmware Development of NFC Embedded Devices, PCB Design with KiCAD, Software Development and UX Design for NFC User flows.</div>
            </Card.Item>
          </Card>

          <Card title="London Drugs">
            <Card.Item>Computer Technician
              <div className="text-md font-bold">Calgary, AB</div>
              <div className="text-sm">Nov 2017 - May 2021</div>
            </Card.Item>
            <hr />
            <Card.Item>
              <div className="text-xs">Apple Certified Technician, specializing in diagnosing and repairing hardware/software issues for both Apple and non-Apple devices while adhering to precise repair procedures.</div>
            </Card.Item>
          </Card>

          <Card title="MacEwan Univeristy">
            <Card.Item>Research Assistant, Teaching Assistant
              <div className="text-md font-bold">Edmonton, AB</div>
              <div className="text-sm">Nov 2017 - May 2021</div>
            </Card.Item>
            <hr />
            <Card.Item>
              <div className="text-xs">- Summer 2024 Research in Mathematics with Dr. Christopher Ramsey (NSERC Discovery Grant 2019-05430)</div>
              <div className="text-xs">- Grader for MATH 311: Complex Analysis, MATH 115: Calculus II</div>
            </Card.Item>
          </Card>

          <Card title="Student Organization of Aerospace Research (SOAR)">
            <Card.Item>Admin Team, Payload Team
              <div className="text-md font-bold">Calgary, AB</div>
              <div className="text-sm">Sep 2019 - May 2021</div>
            </Card.Item>
            <hr />
            <Card.Item>
              <div className="text-xs">- Designed payloads to be carried out during rocket launches. Tested payloads before launches using high altitude balloons.</div>
              <div className="text-xs">- Designed air-brakes with Avionics Team to ensure that rocket reaches a given altitude as accurately as possible.</div>
            </Card.Item>
          </Card>

          <Card title="Mathematics and Statistics Club (MASC)">
            <Card.Item>Treasurer
              <div className="text-md font-bold">Edmonton, AB</div>
              <div className="text-sm">Sep 2023 - Sep 2024</div>
            </Card.Item>
            <hr />
            <Card.Item>
              <div className="text-xs">- Collaborating with other executive members in overseeing the planning and execution of fundraising activities, while ensuring that all financial records are kept up to date and accurate.</div>
              <div className="text-xs">- Mostly just having fun.</div>
            </Card.Item>
          </Card>


          <Card title="Papers">
            <Card.Item>
              📃{' '}
              <a className="text-sm" href="/" target="_blank">
                (Unpublished) Edmonton Urban Heat Island Study and Predictions
              </a>
            </Card.Item>
            <Card.Item>
              📃{' '}
              <a className="text-sm" href="https://journals.macewan.ca/muse/article/view/2867" target="_blank">
                (Published) Failure Rate of Matrix Triangle Inequality
              </a>
            </Card.Item>
            <Card.Item>
              📃{' '}
              <a className="text-sm" href="/" target="_blank">
                (Unpublished) Composing Inner Product Changing Channels
              </a>
            </Card.Item>
          </Card>

          <Card title="Projects">
            <Card.Item>
              📖{' '}
              <a href="https://github.com/ohjime/cosound">
                Cosound
              </a>
            </Card.Item>

            <Card.Item>
              📖{' '}
              <a href="https://github.com/ohjime/tutorlm">
                TutorLM
              </a>
            </Card.Item>


            <Card.Item>
              📖{' '}
              <a href="https://github.com/ohjime/wagon">
                Wagon
              </a>
            </Card.Item>

          </Card>

        </div>
      </div>
    </Layout>
  )
}

export default Index
