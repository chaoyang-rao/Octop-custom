import AppKit

@main
struct PoseScaleCheck {
    static func main() {
        CompanionWindowPlacement.selfTest()
        for side in [79.0, 158.0, 395.0] {
            for sourceHead in [0.6, 0.69] {
                let pose = PetPeek(frame:"fixture.png",crop:[0.2,0.1,0.5,0.8],grip:0.9,headWidth:sourceHead,retraction:0.18,gripRects:[],rotation:nil,pivot:nil)
                let size = pose.size(for:side,referenceHeadWidth:0.52)
                let renderedHead = size.width / pose.normalizedCrop!.width * pose.headWidth
                precondition(abs(renderedHead-side*0.52) < 0.0001)
            }
        }
        let registration = PetRegistration(headWidth:0.52,frames:["fixture":[0.1,0.2,0.8,0.9]],anchor:nil)
        let rect = registration.rect(for:"fixture",in:NSRect(x:10,y:20,width:100,height:100))!
        precondition(abs(rect.minX-20) < 0.0001 && abs(rect.minY-10) < 0.0001)
        precondition(abs(rect.width-80) < 0.0001 && abs(rect.height-90) < 0.0001)
        print("shared_character_scale_and_registered_anchor=passed")
    }
}
